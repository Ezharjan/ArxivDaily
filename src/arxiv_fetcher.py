"""Fetch new papers from arXiv (standard library only).

Two sources:

* **RSS** (default) - ``https://rss.arxiv.org/rss/cs.LG+cs.CL``. Exactly the
  papers in arXiv's latest daily announcement for those categories, in a
  single request. Refreshed every night at midnight US Eastern time; empty on
  Saturdays and Sundays, because arXiv makes no announcements on Friday and
  Saturday evenings.
* **API** - ``https://export.arxiv.org/api/query``. A keyword search over the
  last few days. Used when RSS is unavailable, when no categories are
  configured, or when ``fetch.source`` is ``"api"``. The API is rate-limited
  (HTTP 429), so requests are paced (one every 3+ seconds, as arXiv asks) and
  retried with backoff.
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import http.client
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import __version__, taxonomy
from .textutil import clean, split_authors

log = logging.getLogger(__name__)

RSS_URL = "https://rss.arxiv.org/rss/"
API_URL = "https://export.arxiv.org/api/query"
RSS_ITEM_LIMIT = 2000           # arXiv truncates a single feed at 2000 items
ANNOUNCE_ORDER = {"new": 0, "cross": 1, "replace": 2, "replace-cross": 3}

_sleep = time.sleep             # replaced in tests


@dataclass
class Paper:
    """One arXiv paper, as much as the digest and the web archive need."""

    short_id: str                       # "2405.01234" (no version)
    version: int
    title: str
    summary: str
    authors: List[str]
    primary_category: str
    categories: List[str]
    announce_type: str = "new"          # new | cross | replace | replace-cross
    published: Optional[_dt.datetime] = None
    updated: Optional[_dt.datetime] = None
    matched_keywords: List[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.short_id}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.short_id}"

    def to_dict(self) -> dict:
        """Compact form stored in the web archive."""
        return {
            "id": self.short_id,
            "v": self.version,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.summary,
            "cats": [c for c in (self.categories or [self.primary_category]) if c],
            "type": self.announce_type,
            "kw": self.matched_keywords,
            "score": self.score,
        }


class FetchError(Exception):
    """arXiv could not be reached or returned something unusable."""


@dataclass
class FetchResult:
    papers: List[Paper]
    source: str                         # "rss" or "api"
    announced: Optional[_dt.date] = None  # date of the arXiv announcement (RSS)
    notes: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _user_agent() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY") or "Ezharjan/ArxivDaily"
    return f"ArxivDaily/{__version__} (+https://github.com/{repo})"


def http_get(url: str, *, waits: Sequence[float] = (5, 15, 30), timeout: float = 60) -> bytes:
    """GET ``url``; retry on rate limiting, server errors and network hiccups."""
    attempts = len(waits) + 1
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            e.close()
            retryable = e.code in (429, 500, 502, 503, 504)
            if not retryable or last:
                reason = "rate limit reached (HTTP 429)" if e.code == 429 else f"HTTP {e.code}"
                raise FetchError(f"{reason} from {urllib.parse.urlsplit(url).netloc}") from None
            wait = waits[attempt]
            retry_after = (e.headers or {}).get("Retry-After", "")
            if retry_after.isdigit():
                wait = min(max(float(retry_after), wait), 120)
            log.warning("arXiv answered HTTP %s; retrying in %.0f s (attempt %d of %d)",
                        e.code, wait, attempt + 2, attempts)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            if last:
                reason = getattr(e, "reason", e)
                raise FetchError(f"could not connect to {urllib.parse.urlsplit(url).netloc} ({reason})") from None
            wait = waits[attempt]
            log.warning("network error (%s); retrying in %.0f s", getattr(e, "reason", e), wait)
        _sleep(wait)
    raise FetchError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #

_NS = {
    "arxiv": "http://arxiv.org/schemas/atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
_RSS_DESC_RE = re.compile(r"\s*arXiv:(\S+?)(?:v(\d+))?\s+Announce Type:\s*(\S+)\s*(?:Abstract:\s*)?(.*)", re.S)


def _better(a: Paper, b: Paper) -> Paper:
    """Of two listings of the same paper, keep the more 'new' one."""
    return a if ANNOUNCE_ORDER.get(a.announce_type, 9) <= ANNOUNCE_ORDER.get(b.announce_type, 9) else b


def _dedupe(papers: Iterable[Paper]) -> List[Paper]:
    by_id: Dict[str, Paper] = {}
    for p in papers:
        by_id[p.short_id] = _better(by_id[p.short_id], p) if p.short_id in by_id else p
    return list(by_id.values())


def parse_rss(data: bytes) -> Tuple[List[Paper], Optional[_dt.date]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise FetchError(f"arXiv RSS returned something that isn't RSS ({e})") from None
    channel = root.find("channel")
    if channel is None:
        raise FetchError("arXiv RSS response has no <channel>")
    announced = None
    pub = channel.findtext("pubDate")
    if pub:
        try:
            announced = email.utils.parsedate_to_datetime(pub).date()
        except (TypeError, ValueError):
            pass
    papers = []
    for item in channel.iter("item"):
        desc = item.findtext("description") or ""
        m = _RSS_DESC_RE.match(desc)
        if m:
            arxiv_id, version, atype, abstract = m.group(1), int(m.group(2) or 1), m.group(3), m.group(4)
        else:
            link = item.findtext("link") or ""
            arxiv_id, version, atype, abstract = link.rsplit("/abs/", 1)[-1], 1, "new", desc
        atype = (item.findtext("arxiv:announce_type", namespaces=_NS) or atype).strip().lower()
        cats = [c.text.strip() for c in item.findall("category") if c.text and c.text.strip()]
        if not arxiv_id:
            continue
        papers.append(Paper(
            short_id=arxiv_id.strip(), version=version, title=clean(item.findtext("title") or ""),
            summary=clean(abstract), authors=split_authors(item.findtext("dc:creator", namespaces=_NS) or ""),
            primary_category=cats[0] if cats else "", categories=cats, announce_type=atype,
        ))
    return papers, announced


def fetch_rss(categories: Sequence[str]) -> FetchResult:
    url = RSS_URL + "+".join(categories)
    log.info("Fetching arXiv RSS: %s", url)
    papers, announced = parse_rss(http_get(url))
    if len(papers) >= RSS_ITEM_LIMIT - 10 and len(categories) > 1:
        log.info("Combined feed hit arXiv's %d-item limit; fetching categories one by one", RSS_ITEM_LIMIT)
        for cat in categories:
            _sleep(1)
            more, _ = parse_rss(http_get(RSS_URL + cat))
            papers.extend(more)
    papers = _dedupe(papers)
    log.info("RSS: %d papers in the %s announcement", len(papers), announced or "latest")
    return FetchResult(papers=papers, source="rss", announced=announced)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

def _expand_categories(categories: Sequence[str]) -> List[str]:
    out: List[str] = []
    for c in categories:
        subs = taxonomy.subcategories(c) if c in taxonomy.ARCHIVES else []
        out.extend(subs or [c])
    return list(dict.fromkeys(out))


def _phrase_variants(phrase: str) -> List[str]:
    """'diffusion model' -> ['diffusion model', 'diffusion models'] (and back)."""
    words = phrase.split()
    last = words[-1]
    variants = [phrase]
    if last.isalpha() and len(last) > 2:
        other = last[:-1] if last.lower().endswith("s") and len(last) > 3 else last + "s"
        variants.append(" ".join(words[:-1] + [other]))
    return variants


def build_api_query(keywords: Sequence[str], categories: Sequence[str]) -> str:
    clauses = []
    for kw in keywords:
        phrase = " ".join(re.sub(r'["()\\:\[\]{}^~*?]', " ", kw).replace("-", " ").split())
        if not phrase:
            continue
        for v in _phrase_variants(phrase):
            clauses.append(f'ti:"{v}"')
            clauses.append(f'abs:"{v}"')
    query = "(" + " OR ".join(clauses) + ")"
    cats = _expand_categories(categories)
    if cats:
        query += " AND (" + " OR ".join(f"cat:{c}" for c in cats) + ")"
    return query


def _parse_time(s: Optional[str]) -> Optional[_dt.datetime]:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_api(data: bytes, categories: Sequence[str] = ()) -> List[Paper]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise FetchError(f"arXiv API returned something that isn't XML ({e})") from None
    ns = {"a": "http://www.w3.org/2005/Atom", **_NS}
    wanted = set(_expand_categories(categories))
    papers = []
    for entry in root.findall("a:entry", ns):
        entry_id = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        if "/api/errors" in entry_id:
            raise FetchError("arXiv API error: " + clean(entry.findtext("a:summary", default="", namespaces=ns)))
        body = entry_id.split("/abs/", 1)[-1]
        m = re.match(r"(.+?)v(\d+)$", body)
        short_id, version = (m.group(1), int(m.group(2))) if m else (body, 1)
        prim = entry.find("arxiv:primary_category", ns)
        cats = [c.get("term", "") for c in entry.findall("a:category", ns) if c.get("term")]
        primary = prim.get("term", "") if prim is not None else (cats[0] if cats else "")
        if primary and (not cats or cats[0] != primary):
            cats = [primary] + [c for c in cats if c != primary]
        atype = "new" if version == 1 else "replace"
        if wanted and primary not in wanted:
            atype = "cross" if version == 1 else "replace-cross"
        papers.append(Paper(
            short_id=short_id, version=version,
            title=clean(entry.findtext("a:title", default="", namespaces=ns)),
            summary=clean(entry.findtext("a:summary", default="", namespaces=ns)),
            authors=[clean(a.findtext("a:name", default="", namespaces=ns)) for a in entry.findall("a:author", ns)],
            primary_category=primary, categories=cats, announce_type=atype,
            published=_parse_time(entry.findtext("a:published", namespaces=ns)),
            updated=_parse_time(entry.findtext("a:updated", namespaces=ns)),
        ))
    return papers


def fetch_api(keywords: Sequence[str], categories: Sequence[str], *, lookback_days: int,
              max_results: int, include_revisions: bool = False) -> FetchResult:
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=lookback_days)
    sort_by = "lastUpdatedDate" if include_revisions else "submittedDate"
    found: List[Paper] = []
    requests = 0
    keywords = [k for k in keywords if k.strip()]
    for i in range(0, len(keywords), 10):          # keep URLs a sensible length
        query = build_api_query(keywords[i:i + 10], categories)
        start = 0
        while start < max_results:
            if requests:
                _sleep(3.1)                         # arXiv: at most one request every 3 s
            size = min(200, max_results - start)
            url = API_URL + "?" + urllib.parse.urlencode({
                "search_query": query, "start": start, "max_results": size,
                "sortBy": sort_by, "sortOrder": "descending",
            })
            log.info("Querying arXiv API (results %d-%d)", start + 1, start + size)
            page = parse_api(http_get(url, waits=(10, 30, 60)), categories)
            requests += 1
            stamps = []
            for p in page:
                stamp = (p.updated if include_revisions else p.published) or p.updated or p.published
                if stamp is None or stamp >= cutoff:
                    found.append(p)
                if stamp is not None:
                    stamps.append(stamp)
            if len(page) < size or (stamps and min(stamps) < cutoff):
                break
            start += size
    papers = _dedupe(found)
    log.info("API: %d papers from the last %d day(s)", len(papers), lookback_days)
    return FetchResult(papers=papers, source="api")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def fetch(cfg, *, fallback_when_empty: bool = False) -> FetchResult:
    """Fetch candidate papers according to ``cfg.fetch.source``.

    ``auto`` uses RSS and falls back to the API if RSS fails. With
    ``fallback_when_empty`` (manual previews/tests) an empty RSS feed - e.g. on
    a weekend - also falls back, so there is something to look at.
    """
    source = cfg.fetch.source

    def api() -> FetchResult:
        return fetch_api(cfg.keywords, cfg.categories, lookback_days=cfg.fetch.lookback_days,
                         max_results=cfg.fetch.max_results, include_revisions=cfg.fetch.include_revisions)

    if source in ("auto", "rss") and cfg.categories:
        try:
            rss = fetch_rss(cfg.categories)
        except FetchError as e:
            if source == "rss":
                raise
            log.warning("RSS unavailable (%s); falling back to the arXiv API", e)
            result = api()
            result.notes.insert(0, f"arXiv's RSS feed was unavailable ({e}), so the arXiv API was used instead.")
            return result
        if rss.papers or source == "rss":
            return rss
        # An empty feed is normal on weekends. On a weekday it can also mean the
        # feed hiccupped, so double-check with the API (harmless: already-sent
        # papers are filtered out later).
        day = rss.announced or _dt.datetime.now(_dt.timezone.utc).date()
        weekday = day.weekday() < 5
        if not (weekday or fallback_when_empty):
            return rss
        try:
            result = api()
        except FetchError as e:
            log.warning("arXiv's feed is empty and the API didn't answer (%s)", e)
            rss.notes.append("arXiv's daily feed was empty and the arXiv API didn't respond, "
                             "so there was nothing to check this time.")
            return rss
        result.notes.insert(0, "arXiv's daily feed was empty, so recent papers were searched instead."
                            if weekday else "arXiv doesn't announce new papers on weekends, so recent "
                            "papers were searched instead.")
        return result
    return api()


def filter_announce_types(papers: Iterable[Paper], *, include_cross_lists: bool,
                          include_revisions: bool) -> List[Paper]:
    allowed = {"new"}
    if include_cross_lists:
        allowed.add("cross")
    if include_revisions:
        allowed.add("replace")
        if include_cross_lists:
            allowed.add("replace-cross")
    return [p for p in papers if p.announce_type in allowed]
