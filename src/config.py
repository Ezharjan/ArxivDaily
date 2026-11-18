"""Load and validate config.json, with error messages written for humans.

Everything except ``keywords`` has a sensible default, so a minimal config is::

    {"keywords": ["diffusion model"], "categories": ["cs.CV"]}

The loader also forgives the two mistakes people make most often when editing
JSON by hand (``// comments`` and a trailing comma) and points at the exact
line and column for anything it cannot fix.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import taxonomy

DEFAULT_SUBJECT = "[ArxivDaily] {n_papers} new {papers} — {date}"

DEFAULTS: Dict[str, Any] = {
    "keywords": [],
    "categories": [],
    "recipients": [],
    "fetch": {
        "source": "auto",            # auto | rss | api
        "include_cross_lists": True,
        "include_revisions": False,
        "lookback_days": 5,          # API source only; Monday's mailing reaches back ~3.5 days
        "max_results": 500,          # API source only
    },
    "ranking": {
        "max_papers_per_email": 25,
        "min_score": 1.0,
        "title_weight": 3.0,
        "abstract_weight": 1.0,
        "multi_keyword_bonus": 0.5,
    },
    "email": {
        "from_name": "ArxivDaily",
        "from_address": "",
        "subject_template": DEFAULT_SUBJECT,
        "abstract_chars": 320,
        "include_authors_max": 5,
    },
    "archive": {
        "keep_days": 90,
        "max_papers_per_day": 200,
    },
}

# Settings from version 1 that are accepted (with a reminder) but no longer have any effect.
_LEGACY = {
    ("fetch", "max_results_per_keyword"): "was replaced by \"fetch.max_results\"",
    ("fetch", "sort_by"): "no longer has an effect (papers are always fetched newest first)",
}
_IGNORED_TOP_LEVEL = {"$schema", "_comment", "comment", "notes"}

_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class ConfigError(Exception):
    """A problem in config.json that the user has to fix."""

    def __init__(self, message: str, *, path: str = "config.json", line: int = 0, column: int = 0):
        super().__init__(message)
        self.path = path
        self.line = line
        self.column = column


@dataclass
class FetchSettings:
    source: str
    include_cross_lists: bool
    include_revisions: bool
    lookback_days: int
    max_results: int


@dataclass
class RankingSettings:
    max_papers_per_email: int
    min_score: float
    title_weight: float
    abstract_weight: float
    multi_keyword_bonus: float


@dataclass
class EmailSettings:
    from_name: str
    from_address: str
    subject_template: str
    abstract_chars: int
    include_authors_max: int


@dataclass
class ArchiveSettings:
    keep_days: int
    max_papers_per_day: int


@dataclass
class Config:
    keywords: List[str]
    categories: List[str]
    recipients: List[str]
    fetch: FetchSettings
    ranking: RankingSettings
    email: EmailSettings
    archive: ArchiveSettings
    path: str = "config.json"
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# .env support (local runs only; GitHub Actions uses repository secrets)
# --------------------------------------------------------------------------- #

def load_dotenv(path: str) -> List[str]:
    """Read KEY=VALUE lines from ``path`` into os.environ (never overriding).

    Returns the names that were set. Missing file -> nothing happens.
    """
    if not os.path.isfile(path):
        return []
    loaded = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:                      # trailing comment
                value = value.split(" #", 1)[0].rstrip()
            if key and key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded


# --------------------------------------------------------------------------- #
# JSON parsing with friendly errors
# --------------------------------------------------------------------------- #

def _blank_comments_and_trailing_commas(text: str) -> str:
    """Replace // and /* */ comments and trailing commas with spaces.

    Offsets are preserved (newlines are kept) so error positions still point
    at the right place in the original file.
    """
    out = list(text)
    i, n = 0, len(text)
    in_str = False
    last_comma = -1          # index of a comma that may turn out to be trailing
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            last_comma = -1
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if text[k] != "\n":
                    out[k] = " "
            i = j
            continue
        elif ch == ",":
            last_comma = i
        elif ch in "]}":
            if last_comma != -1:
                out[last_comma] = " "
            last_comma = -1
        elif not ch.isspace():
            last_comma = -1
        i += 1
    return "".join(out)


_HINTS = [
    ("Expecting ',' delimiter", "A comma is probably missing at the end of the previous item or line."),
    ("Expecting property name enclosed in double quotes",
     'Setting names need straight double quotes, like "keywords" (single quotes don\'t work in JSON).'),
    ("Expecting ':' delimiter", 'Each setting needs a colon between its name and value, like "min_score": 1.0'),
    ("Expecting value", "A value is missing or malformed. Text must be in double quotes; true/false/numbers must not be."),
    ("Unterminated string", "A text value is missing its closing double quote."),
    ("Invalid control character", "A text value is missing its closing double quote."),
    ("Extra data", "There is extra text after the final closing brace }."),
]


def _describe_json_error(text: str, err: json.JSONDecodeError, path: str) -> ConfigError:
    lines = text.splitlines() or [""]
    if not text[err.pos:].strip():            # the problem is at the very end of the file
        body = text.rstrip()
        line_no = body.count("\n") + 1
        col = len(body) - body.rfind("\n")    # just after the last character
        hint = ("The file is empty. It needs at least: {\"keywords\": [\"your topic\"]}" if not body else
                "The file ends too early: a closing } or ] is probably missing.")
    else:
        line_no = max(1, min(err.lineno, len(lines)))
        col = max(1, err.colno)
        hint = next((h for key, h in _HINTS if err.msg.startswith(key)), "")
        if any(q in lines[line_no - 1] for q in "“”„‘’"):     # curly quotes where the parser gave up
            hint = "Replace the curly quotes (“ ” ‘ ’) with straight double quotes (\")."
    snippet = []
    for ln in range(max(1, line_no - 1), line_no + 1):
        snippet.append(f"  {ln:>4} | {lines[ln - 1]}")
    snippet.append("       | " + " " * (col - 1) + "^")
    reason = re.sub(r"\s+(?:starting\s+)?at$", "", err.msg)    # "Unterminated string starting at" -> "...string"
    msg = (f"{os.path.basename(path)} is not valid JSON (line {line_no}, column {col}: {reason}).\n"
           + "\n".join(snippet)
           + (f"\n  Hint: {hint}" if hint else ""))
    return ConfigError(msg, path=path, line=line_no, column=col)


def parse_json(text: str, path: str = "config.json") -> "tuple[dict, bool]":
    """Parse JSON, tolerating comments/trailing commas. Returns (data, was_lenient)."""
    try:
        data = json.loads(text)
        lenient = False
    except json.JSONDecodeError:
        relaxed = _blank_comments_and_trailing_commas(text)
        try:
            data = json.loads(relaxed)
            lenient = True
        except json.JSONDecodeError as err:
            raise _describe_json_error(text, err, path) from None
    if not isinstance(data, dict):
        raise ConfigError(f"{os.path.basename(path)} must contain a JSON object: {{ ... }}", path=path, line=1, column=1)
    return data, lenient


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _suggest(name: str, options) -> str:
    match = difflib.get_close_matches(name, list(options), n=1, cutoff=0.6)
    return f' Did you mean "{match[0]}"?' if match else ""


def _line_of(text: str, needle: str) -> int:
    idx = text.find(f'"{needle}"')
    return text.count("\n", 0, idx) + 1 if idx >= 0 else 0


def _str_list(value: Any, name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f'"{name}" must be a list of text values, like ["a", "b"].')
    return [v.strip() for v in value if v and v.strip()]


def _number(section: dict, key: str, kind, *, minimum=None, where: str = ""):
    value = section[key]
    label = f"{where}.{key}" if where else key
    if isinstance(value, bool):
        raise ConfigError(f'"{label}" must be a number, not true/false.')
    try:
        value = kind(value)
    except (TypeError, ValueError):
        raise ConfigError(f'"{label}" must be a number (got {value!r}).') from None
    if minimum is not None and value < minimum:
        raise ConfigError(f'"{label}" must be at least {minimum} (got {value}).')
    return value


def _bool(section: dict, key: str, where: str) -> bool:
    value = section[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
        return value.strip().lower() in ("true", "yes")
    raise ConfigError(f'"{where}.{key}" must be true or false (got {value!r}).')


def _merge(defaults: dict, data: dict, warnings: List[str], where: str = "") -> dict:
    merged = copy.deepcopy(defaults)
    for key, value in data.items():
        dotted = f"{where}.{key}" if where else key
        if not where and key in _IGNORED_TOP_LEVEL:
            continue
        if (where, key) in _LEGACY:
            warnings.append(f'"{dotted}" is from version 1 and {_LEGACY[(where, key)]}. You can delete it.')
            continue
        if key not in defaults:
            warnings.append(f'Unknown setting "{dotted}" is ignored.{_suggest(key, defaults.keys())}')
            continue
        if isinstance(defaults[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f'"{dotted}" must be an object: {{ ... }}')
            merged[key] = _merge(defaults[key], value, warnings, dotted)
        else:
            merged[key] = value
    return merged


def _validate_categories(raw: List[str]) -> List[str]:
    lower = {c.lower(): c for c in list(taxonomy.CATEGORIES) + list(taxonomy.ARCHIVES)}
    out = []
    for cat in raw:
        if taxonomy.is_valid(cat):
            out.append(cat)
            continue
        fixed = lower.get(cat.lower())
        hint = f' Did you mean "{fixed}"? (category codes are case-sensitive)' if fixed else _suggest(cat, lower.values())
        raise ConfigError(f'Unknown arXiv category "{cat}".{hint} '
                          "Full list: https://arxiv.org/category_taxonomy")
    return list(dict.fromkeys(out))


def validate(data: dict, path: str = "config.json", text: str = "") -> Config:
    warnings: List[str] = []
    try:
        merged = _merge(DEFAULTS, data, warnings)

        keywords = _str_list(merged["keywords"], "keywords")
        if not keywords:
            raise ConfigError('Add at least one entry to "keywords", e.g. "keywords": ["diffusion model"].')
        seen, unique = set(), []
        for kw in keywords:
            if kw.lower() in seen:
                warnings.append(f'Keyword "{kw}" is listed twice; the duplicate is ignored.')
                continue
            seen.add(kw.lower())
            unique.append(kw)

        categories = _validate_categories(_str_list(merged["categories"], "categories"))

        recipients = _str_list(merged["recipients"], "recipients")
        for addr in recipients:
            if not _EMAIL_RE.match(addr):
                raise ConfigError(f'"{addr}" in "recipients" is not a valid email address.')

        f = merged["fetch"]
        source = str(f["source"]).strip().lower()
        if source not in ("auto", "rss", "api"):
            raise ConfigError(f'"fetch.source" must be "auto", "rss" or "api" (got "{f["source"]}").')
        if source == "rss" and not categories:
            raise ConfigError('"fetch.source" is "rss", which needs at least one entry in "categories".')
        fetch = FetchSettings(
            source=source,
            include_cross_lists=_bool(f, "include_cross_lists", "fetch"),
            include_revisions=_bool(f, "include_revisions", "fetch"),
            lookback_days=_number(f, "lookback_days", int, minimum=1, where="fetch"),
            max_results=min(_number(f, "max_results", int, minimum=1, where="fetch"), 2000),
        )

        r = merged["ranking"]
        ranking = RankingSettings(
            max_papers_per_email=_number(r, "max_papers_per_email", int, minimum=1, where="ranking"),
            min_score=_number(r, "min_score", float, minimum=0, where="ranking"),
            title_weight=_number(r, "title_weight", float, minimum=0, where="ranking"),
            abstract_weight=_number(r, "abstract_weight", float, minimum=0, where="ranking"),
            multi_keyword_bonus=_number(r, "multi_keyword_bonus", float, minimum=0, where="ranking"),
        )

        e = merged["email"]
        subject = str(e["subject_template"] or DEFAULT_SUBJECT)
        try:
            subject.format(n_papers=1, papers="paper", date="2026-01-01")
        except (KeyError, IndexError, ValueError) as err:
            raise ConfigError(f'"email.subject_template" has an unknown placeholder ({err}). '
                              "Available: {n_papers}, {papers}, {date}.") from None
        from_address = str(e["from_address"] or "").strip()
        if from_address and not _EMAIL_RE.match(from_address):
            raise ConfigError(f'"email.from_address" is not a valid email address: "{from_address}".')
        email = EmailSettings(
            from_name=str(e["from_name"] or "ArxivDaily").strip(),
            from_address=from_address,
            subject_template=subject,
            abstract_chars=_number(e, "abstract_chars", int, minimum=0, where="email"),
            include_authors_max=_number(e, "include_authors_max", int, minimum=0, where="email"),
        )

        a = merged["archive"]
        archive = ArchiveSettings(
            keep_days=_number(a, "keep_days", int, minimum=1, where="archive"),
            max_papers_per_day=_number(a, "max_papers_per_day", int, minimum=1, where="archive"),
        )
    except ConfigError as err:
        err.path = path
        if not err.line and text:
            m = re.search(r'"([^"\s]+)"', str(err))
            if m:
                token = m.group(1)
                err.line = _line_of(text, token) or _line_of(text, token.split(".")[-1])
        raise

    return Config(keywords=unique, categories=categories, recipients=recipients, fetch=fetch,
                  ranking=ranking, email=email, archive=archive, path=path, warnings=warnings)


def load_config(path: str) -> Config:
    if not os.path.isfile(path):
        raise ConfigError(f"Can't find {path}. It should sit next to main.py.", path=path)
    with open(path, "r", encoding="utf-8-sig") as f:      # -sig: tolerate Notepad's BOM
        text = f.read()
    data, lenient = parse_json(text, path)
    cfg = validate(data, path, text)
    if lenient:
        cfg.warnings.insert(0, f"{os.path.basename(path)} contains comments or trailing commas. "
                               "ArxivDaily accepts them, but strict JSON tools may not.")
    return cfg


def resolve_recipients(cfg: Config, fallback: str = "") -> "tuple[List[str], str]":
    """Who gets the digest, and where that list came from.

    Order: MAIL_TO secret/env > config.json "recipients" > the sending account.
    """
    env = os.environ.get("MAIL_TO", "")
    if env.strip():
        addrs = [a.strip() for a in re.split(r"[,;\s]+", env) if a.strip()]
        bad = [a for a in addrs if not _EMAIL_RE.match(a)]
        if bad:
            what = "an entry that isn't an email address" if len(bad) == 1 else \
                f"{len(bad)} entries that aren't email addresses"
            raise ConfigError(f"The MAIL_TO secret contains {what}. Write full addresses separated by "
                              "commas, e.g. a@x.com, b@y.org.", path="MAIL_TO")
        return list(dict.fromkeys(addrs)), "MAIL_TO secret"
    if cfg.recipients:
        return cfg.recipients, "config.json"
    if fallback:
        return [fallback], "your sending address"
    return [], ""


def mask_email(addr: str) -> str:
    """'alice@example.com' -> 'al***@example.com' (safe for public logs)."""
    if "@" not in addr:
        return "***"
    user, domain = addr.split("@", 1)
    return (user[:2] if len(user) > 2 else user[:1]) + "***@" + domain


def env_flag(name: str) -> Optional[bool]:
    value = os.environ.get(name, "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return None
