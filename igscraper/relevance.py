"""Niche-relevance check.

Assignment of an account to a niche used to be pure provenance ("this account
appeared under #tag"). This module measures whether an account's *own* posts
actually talk about the niche, using the captions ``enrich`` already fetches
(no extra requests). Flag-only by default — it never silently drops a lead.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Set, Tuple

from .config import Config, Niche

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Tags/words too generic to prove niche fit on their own.
GENERIC = {
    "gift", "gifts", "gifting", "fyp", "foryou", "foryoupage", "viral", "trending",
    "reels", "explore", "explorepage", "love", "instagood", "photooftheday",
    "follow", "followme", "like", "shop", "shopping", "store", "smallbusiness",
    "smallbiz", "handmade", "buy", "sale", "the", "and", "for", "with",
}


def _tokens(text: str) -> Set[str]:
    """Lowercase alnum tokens; '#new-bag' -> {'new', 'bag'}."""
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2 and t not in GENERIC}


def niche_keywords(niche: Niche, config: Config) -> Set[str]:
    """Keyword set that defines a niche, from name + tags + explicit keywords."""
    kws: Set[str] = set(_tokens(niche.name))
    for tag in niche.hashtags:
        kws |= _tokens(tag)
    kws |= set(niche.relevance_keywords)
    extra = (
        config.discovery.get("relevance", {})
        .get("keywords_by_niche", {})
        .get(niche.name, [])
    )
    for kw in extra or []:
        kws |= _tokens(str(kw))
    return kws


def keywords_by_niche(config: Config) -> Dict[str, Set[str]]:
    return {n.name: niche_keywords(n, config) for n in config.niches if n.name}


def _score(captions: Iterable[str], keywords: Set[str]) -> Tuple[int, List[str]]:
    if not keywords:
        return 0, []
    matched: Set[str] = set()
    hits = 0
    for caption in captions:
        overlap = _tokens(caption) & keywords
        if overlap:
            hits += 1
            matched |= overlap
    return hits, sorted(matched)


def verify_row(
    row: Dict,
    kw_by_niche: Dict[str, Set[str]],
    min_overlap: int,
) -> Dict:
    """Annotate a row with relevance to the niche(s) it was discovered in."""
    captions = row.get("_sample_captions") or []
    kws: Set[str] = set()
    for niche_name in row.get("niches") or []:
        kws |= kw_by_niche.get(niche_name, set())
    hits, matched = _score(captions, kws)
    row["relevance_hits"] = hits
    row["relevance_matched"] = ", ".join(matched[:8])
    row["relevance_flagged"] = hits < int(min_overlap)
    return row
