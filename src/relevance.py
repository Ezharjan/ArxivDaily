"""Relevance scoring for fetched arXiv papers.

Each paper is scored against every configured keyword. A keyword hit in the
title is weighted more heavily than one in the abstract. Papers matching
multiple distinct keywords get a small bonus. Phrase matches are anchored
on word boundaries so "gpt" doesn't spuriously match "egypt".
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence

from .arxiv_fetcher import Paper


_TOKEN_SPLIT = re.compile(r"[\s\-]+")


def _make_pattern(keyword: str) -> re.Pattern:
    """Case-insensitive phrase match with relaxed inter-token separation.

    Hyphens and whitespace are treated as interchangeable, so a configured
    keyword like "in-context learning" matches all of:
      - "in-context learning"
      - "In Context Learning"
      - "in - context learning"
    Word boundaries prevent spurious matches inside larger words
    ("gpt" must not match "egypt").
    """
    parts = [re.escape(tok) for tok in _TOKEN_SPLIT.split(keyword.strip()) if tok]
    if not parts:
        return re.compile(r"$.^")
    body = r"[\s\-]+".join(parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def _count(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text or ""))


def score_paper(
    paper: Paper,
    keywords: Sequence[str],
    title_weight: float = 3.0,
    abstract_weight: float = 1.0,
    multi_keyword_bonus: float = 0.5,
) -> None:
    """Mutates ``paper`` in place: sets ``paper.score`` and ``paper.matched_keywords``."""
    score = 0.0
    matched: List[str] = []
    title = paper.title or ""
    abstract = paper.summary or ""
    for kw in keywords:
        if not kw or not kw.strip():
            continue
        pat = _make_pattern(kw)
        t = _count(pat, title)
        a = _count(pat, abstract)
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
    """Score every paper, drop those below ``min_score``, return top N."""
    scored: List[Paper] = []
    for p in papers:
        score_paper(
            p,
            keywords,
            title_weight=title_weight,
            abstract_weight=abstract_weight,
            multi_keyword_bonus=multi_keyword_bonus,
        )
        if p.score >= min_score:
            scored.append(p)
    scored.sort(key=lambda p: (p.score, p.updated.timestamp()), reverse=True)
    if max_papers is not None and max_papers > 0:
        scored = scored[:max_papers]
    return scored
