"""Relevance scoring for fetched arXiv papers.

Each paper is scored against every configured keyword. A keyword hit in the
title is weighted more heavily than one in the abstract. Papers matching
multiple distinct keywords get a small bonus.

Matching is forgiving in the ways that matter for paper titles:

* case-insensitive: "Diffusion Model" == "diffusion model"
* hyphens, spaces and slashes are interchangeable, and may be omitted:
  "in-context learning" == "in context learning" == "incontext learning"
* singular and plural forms of the last word both match:
  "diffusion model" also finds "Diffusion Models"; "LLMs" also finds "LLM"
* whole words only: "gpt" does not match "egypt"
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Tuple

from .arxiv_fetcher import ANNOUNCE_ORDER, Paper

_TOKEN_SPLIT = re.compile(r"[\s\-‐-―_/]+")
_SEP = r"[\s\-‐-―_/]*"


def _last_word(tok: str) -> str:
    """Regex for the final word of a keyword, accepting singular and plural."""
    esc = re.escape(tok)
    low = tok.lower()
    if not tok.isalpha() or len(tok) < 3:
        return esc
    if low.endswith("ies") and len(low) > 4:                       # strategies
        return re.escape(tok[:-3]) + "(?:y|ies)"
    if low.endswith("es") and len(low) > 4:                        # caches, approaches, biases
        return f"(?:{re.escape(tok[:-2])}(?:es)?|{re.escape(tok[:-1])}s?)"
    if low.endswith("is") and len(low) > 4:                        # analysis / analyses
        return re.escape(tok[:-2]) + "(?:is|es)"
    if low.endswith(("ss", "us", "as", "x", "z", "ch", "sh")):     # loss, corpus, bias, patch
        return esc + "(?:es)?"
    if low.endswith("s"):                                          # models, experts, LLMs
        return re.escape(tok[:-1]) + "s?"
    if low.endswith("y") and low[-2] not in "aeiou":               # strategy
        return re.escape(tok[:-1]) + "(?:y|ies)"
    return esc + "s?"                                              # model, transformer, LLM


def make_pattern(keyword: str) -> "re.Pattern[str]":
    parts = [tok for tok in _TOKEN_SPLIT.split(keyword.strip()) if tok]
    if not parts:
        return re.compile(r"$.^")
    body = _SEP.join([re.escape(t) for t in parts[:-1]] + [_last_word(parts[-1])])
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def compile_keywords(keywords: Sequence[str]) -> List[Tuple[str, "re.Pattern[str]"]]:
    return [(kw, make_pattern(kw)) for kw in keywords if kw and kw.strip()]


def score_paper(
    paper: Paper,
    keywords: Sequence[str],
    title_weight: float = 3.0,
    abstract_weight: float = 1.0,
    multi_keyword_bonus: float = 0.5,
    *,
    patterns=None,
) -> None:
    """Mutates ``paper`` in place: sets ``paper.score`` and ``paper.matched_keywords``."""
    patterns = patterns or compile_keywords(keywords)
    score = 0.0
    matched: List[str] = []
    for kw, pat in patterns:
        t = len(pat.findall(paper.title or ""))
        a = len(pat.findall(paper.summary or ""))
        if t == 0 and a == 0:
            continue
        score += title_weight * t + abstract_weight * a
        matched.append(kw)
    if len(matched) > 1:
        score += multi_keyword_bonus * (len(matched) - 1)
    paper.matched_keywords = matched
    paper.score = round(score, 3)


def score_and_rank(
    papers: Iterable[Paper],
    keywords: Sequence[str],
    *,
    title_weight: float = 3.0,
    abstract_weight: float = 1.0,
    multi_keyword_bonus: float = 0.5,
    min_score: float = 1.0,
    max_papers=None,
) -> List[Paper]:
    """Score every paper, drop those below ``min_score``, best first (top N if given)."""
    patterns = compile_keywords(keywords)
    scored: List[Paper] = []
    for p in papers:
        score_paper(p, keywords, title_weight, abstract_weight, multi_keyword_bonus, patterns=patterns)
        if p.matched_keywords and p.score >= min_score:
            scored.append(p)
    scored.sort(key=lambda p: (-p.score, ANNOUNCE_ORDER.get(p.announce_type, 9), _id_sort_key(p.short_id)))
    if max_papers is not None and max_papers > 0:
        scored = scored[:max_papers]
    return scored


def _id_sort_key(short_id: str):
    """Newer arXiv ids first ("2511.01234" > "2510.09999")."""
    digits = re.sub(r"\D", "", short_id)
    return -int(digits) if digits else 0


def keyword_counts(papers: Iterable[Paper], keywords: Sequence[str]) -> Dict[str, int]:
    counts = {kw: 0 for kw in keywords}
    for p in papers:
        for kw in p.matched_keywords:
            counts[kw] = counts.get(kw, 0) + 1
    return counts


def highlight_spans(text: str, patterns) -> List[Tuple[int, int, int]]:
    """Non-overlapping (start, end, keyword_index) matches, left to right."""
    hits = []
    for idx, (_, pat) in enumerate(patterns):
        for m in pat.finditer(text or ""):
            if m.end() > m.start():
                hits.append((m.start(), m.end(), idx))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out, last_end = [], -1
    for start, end, idx in hits:
        if start >= last_end:
            out.append((start, end, idx))
            last_end = end
    return out
