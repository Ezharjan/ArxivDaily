"""arXiv API querying.

Uses the `arxiv` python client (which wraps the official arXiv Atom feed)
to run one search per keyword. Results are deduplicated by arXiv ID,
filtered to the configured categories, and trimmed to the lookback window.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re as _re
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

import arxiv

log = logging.getLogger(__name__)


@dataclass
class Paper:
    """Lightweight, JSON-friendly representation of an arXiv result."""

    entry_id: str
    short_id: str
    title: str
    summary: str
    authors: List[str]
    primary_category: str
    categories: List[str]
    published: _dt.datetime
    updated: _dt.datetime
    pdf_url: str
    abs_url: str
    matched_keywords: List[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "short_id": self.short_id,
            "title": self.title,
            "summary": self.summary,
            "authors": self.authors,
            "primary_category": self.primary_category,
            "categories": self.categories,
            "published": self.published.isoformat(),
            "updated": self.updated.isoformat(),
            "pdf_url": self.pdf_url,
            "abs_url": self.abs_url,
            "matched_keywords": self.matched_keywords,
            "score": self.score,
        }


def _short_id(entry_id: str) -> str:
    """Strip the trailing version suffix from an arXiv entry id.

    Modern ids:  "http://arxiv.org/abs/2405.01234v2" -> "2405.01234"
    Pre-2007:    "http://arxiv.org/abs/math.GT/0309136v2" -> "math.GT/0309136"
    The category prefix on old-style ids is preserved so the short_id remains
    a stable, unique identifier across runs.
    """
    if "/abs/" in entry_id:
        body = entry_id.split("/abs/", 1)[1]
    else:
        body = entry_id.rsplit("/", 1)[-1]
    return _re.sub(r"v\d+$", "", body)


def _build_query(keyword: str, categories: Sequence[str]) -> str:
    kw = keyword.strip().replace('"', "")
    kw_clause = f'(ti:"{kw}" OR abs:"{kw}")'
    if categories:
        cat_clause = " OR ".join(f"cat:{c.strip()}" for c in categories)
        return f"{kw_clause} AND ({cat_clause})"
    return kw_clause


def _sort_criterion(name: str):
    mapping = {
        "submittedDate": arxiv.SortCriterion.SubmittedDate,
        "lastUpdatedDate": arxiv.SortCriterion.LastUpdatedDate,
        "relevance": arxiv.SortCriterion.Relevance,
    }
    return mapping.get(name, arxiv.SortCriterion.SubmittedDate)


def _convert(result) -> Paper:
    return Paper(
        entry_id=result.entry_id,
        short_id=_short_id(result.entry_id),
        title=" ".join(result.title.split()),
        summary=" ".join(result.summary.split()),
        authors=[a.name for a in result.authors],
        primary_category=result.primary_category,
        categories=list(result.categories),
        published=result.published,
        updated=result.updated,
        pdf_url=result.pdf_url,
        abs_url=result.entry_id.replace("/pdf/", "/abs/"),
    )


def fetch_for_keyword(
    keyword: str,
    categories: Sequence[str],
    max_results: int,
    sort_by: str = "submittedDate",
    client=None,
) -> List[Paper]:
    """Run a single keyword search against arXiv."""
    client = client or arxiv.Client(
        page_size=min(max(max_results, 1), 100), delay_seconds=3.0, num_retries=3,
    )
    query = _build_query(keyword, categories)
    log.info("arxiv query: %s (max=%d)", query, max_results)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=_sort_criterion(sort_by),
        sort_order=arxiv.SortOrder.Descending,
    )
    out: List[Paper] = []
    for r in client.results(search):
        try:
            out.append(_convert(r))
        except Exception as e:
            log.warning("skipping malformed result: %s", e)
    return out


def fetch_all(
    keywords: Iterable[str],
    categories: Sequence[str],
    max_results_per_keyword: int,
    sort_by: str = "submittedDate",
    lookback_days=None,
) -> List[Paper]:
    """Run one search per keyword, deduplicate, optionally filter by recency.

    The lookback window is applied against ``updated`` (arXiv's listing date),
    which is what actually drives whether a paper appears in a given listing.
    """
    keyword_list = [k for k in keywords if k and k.strip()]
    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    by_id = {}
    for kw in keyword_list:
        try:
            results = fetch_for_keyword(kw, categories, max_results_per_keyword, sort_by, client=client)
        except Exception as e:
            log.error("query failed for keyword %r: %s", kw, e)
            time.sleep(2)
            continue
        for p in results:
            if p.short_id not in by_id:
                by_id[p.short_id] = p
    papers = list(by_id.values())

    if lookback_days is not None and lookback_days > 0:
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=lookback_days)
        papers = [p for p in papers if p.updated >= cutoff]

    papers.sort(key=lambda p: p.updated, reverse=True)
    log.info("fetched %d unique papers across %d keywords", len(papers), len(keyword_list))
    return papers
