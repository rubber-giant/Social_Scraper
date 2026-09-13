"""Discovery: turn a niche keyword into candidate brand usernames.

Multi-strategy: each niche is expanded through several surfaces (hashtag feeds,
keyword account search, and seed-based lookalike expansion), merged with
provenance, and truncated per niche by provenance weight. The heavy lifting for
each surface lives in :mod:`igscraper.strategies`.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set

from .client import InstagramClient
from .config import Config, Niche
from .models import Candidate, DiscoveryResult
from .strategies import (
    NICHE_STRATEGIES,
    SAFEST_FIRST,
    Budget,
    build_seeds,
)

logger = logging.getLogger("igscraper.discovery")


def slugify_hashtag(name: str) -> str:
    """'Home Decor 2.0' -> 'homedecor20' (hashtag-safe slug)."""
    return re.sub(r"[^a-zA-Z0-9]", "", name.lower())


def niche_hashtags(niche: Niche) -> List[str]:
    """Tags to scan for a niche: slug of the niche + any configured hashtags."""
    tags = [slugify_hashtag(niche.name)]
    tags += [slugify_hashtag(t) for t in niche.hashtags]
    # Keep order but drop empties and duplicates
    seen: Set[str] = set()
    out: List[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _enabled_strategies(config: Config) -> List[str]:
    enabled = config.discovery.get("enabled") or []
    return [s for s in SAFEST_FIRST if s in enabled]


def _apply_source_share(
    members: List[Candidate], max_authors: int, source_share: Dict[str, float]
) -> List[Candidate]:
    """Cap how much of a niche's budget one strategy may claim (by weight order).

    Provenance weighting alone lets the top strategy (``chaining``, weight 2.0)
    fill the whole ``max_authors`` cap, starving the higher-recall surfaces. Here
    each configured strategy may claim at most ``share * max_authors`` slots in
    the first pass; leftover slots are then backfilled best-first, so capacity is
    never wasted when the other strategies don't produce enough.
    """
    caps = {
        strat: int(max_authors * float(frac))
        for strat, frac in (source_share or {}).items()
    }
    if not caps:
        return members[:max_authors]

    admitted: List[Candidate] = []
    counts: Dict[str, int] = {}
    for cand in members:
        if len(admitted) >= max_authors:
            break
        src = cand.primary_source
        strat = src.strategy if src else ""
        cap = caps.get(strat)
        if cap is not None and counts.get(strat, 0) >= cap:
            continue
        admitted.append(cand)
        counts[strat] = counts.get(strat, 0) + 1

    if len(admitted) < max_authors:
        seen = {c.username for c in admitted}
        for cand in members:
            if len(admitted) >= max_authors:
                break
            if cand.username not in seen:
                admitted.append(cand)
                seen.add(cand.username)

    # Keep the curated order weight-desc (stable -> first-pass picks win ties).
    admitted.sort(key=lambda c: c.weight, reverse=True)
    return admitted


def merge_into(
    result: DiscoveryResult,
    niche: Niche,
    candidates: List[Candidate],
    source_share: Optional[Dict[str, float]] = None,
) -> None:
    """Merge a niche's discovered candidates, then cap its list by weight.

    Higher-provenance candidates surface first in ``authors_by_niche``; a stable
    sort means equal-weight candidates keep discovery order (today's behavior).
    ``source_share`` caps how much of the niche budget any one strategy claims.
    """
    for cand in candidates:
        existing = result.candidates.get(cand.username)
        if existing is None:
            result.candidates[cand.username] = cand
            existing = cand
        else:
            for src in cand.sources:
                existing.add_source(src)
            if cand.pk and not existing.pk:
                existing.pk = cand.pk
        existing.niches.add(niche.name)

    members = [c for c in result.candidates.values() if niche.name in c.niches]
    members.sort(key=lambda c: c.weight, reverse=True)
    if niche.max_authors:
        members = _apply_source_share(members, niche.max_authors, source_share or {})
    result.authors_by_niche[niche.name] = [c.username for c in members]


def discover(
    cl: InstagramClient,
    config: Config,
    seed_pool: Optional[Dict[str, List[str]]] = None,
) -> DiscoveryResult:
    """Discover candidate usernames per niche via all enabled strategies.

    ``seed_pool`` maps niche name -> usernames carried over from prior runs;
    they seed the ``chaining`` strategy alongside any manual ``niche.seeds``.
    """
    seed_pool = seed_pool or {}
    max_requests = int(config.discovery.get("max_requests_per_run", 0))
    budget = Budget(max_requests=max_requests)
    enabled = _enabled_strategies(config)
    logger.info(
        "Discovery strategies: %s (request cap: %s)",
        ", ".join(enabled) or "(none)",
        max_requests or "unlimited",
    )

    result = DiscoveryResult()
    for niche in config.niches:
        if not niche.name:
            continue

        collected: List[Candidate] = []
        keyword_candidates: List[Candidate] = []

        for strategy in enabled:
            if strategy == "chaining":
                continue  # needs seeds assembled below
            candidates = NICHE_STRATEGIES[strategy](cl, config, niche, budget, {})
            if strategy == "keyword":
                keyword_candidates = candidates
            collected.extend(candidates)

        if "chaining" in enabled:
            seeds = build_seeds(
                config, niche, seed_pool.get(niche.name, []), keyword_candidates
            )
            if seeds:
                logger.info("  chaining from %d seed(s): %s", len(seeds), ", ".join("@" + s for s in seeds))
                collected.extend(
                    NICHE_STRATEGIES["chaining"](cl, config, niche, budget, {"seeds": seeds})
                )
            else:
                logger.info("Niche '%s': no seeds for chaining; skipping.", niche.name)

        merge_into(
            result,
            niche,
            collected,
            config.discovery.get("source_share", {}) or {},
        )
        logger.info(
            "Niche '%s' -> %d candidates (requests used: %d)",
            niche.name,
            len(result.authors_by_niche.get(niche.name, [])),
            budget.used,
        )

    return result


def plan(
    config: Config, seed_pool: Optional[Dict[str, List[str]]] = None
) -> List[Dict]:
    """Dry-run plan (no network): what each strategy would query and cost."""
    seed_pool = seed_pool or {}
    enabled = _enabled_strategies(config)
    max_requests = int(config.discovery.get("max_requests_per_run", 0))
    out: List[Dict] = []
    for niche in config.niches:
        if not niche.name:
            continue
        strategies: Dict[str, Dict] = {}
        if "hashtag" in enabled:
            tags = niche_hashtags(niche)
            strategies["hashtag"] = {"refs": ["#" + t for t in tags], "est_requests": len(tags)}
        if "keyword" in enabled:
            max_q = int(config.discovery.get("keyword", {}).get("max_queries_per_niche", 4))
            queries = niche.keyword_queries[:max_q]
            strategies["keyword"] = {"refs": queries, "est_requests": len(queries)}
        if "chaining" in enabled:
            seeds = build_seeds(config, niche, seed_pool.get(niche.name, []), [])
            strategies["chaining"] = {
                "refs": ["@" + s for s in seeds],
                "est_requests": 2 * len(seeds),
            }
        out.append(
            {
                "niche": niche.name,
                "strategies": strategies,
                "est_requests": sum(s["est_requests"] for s in strategies.values()),
            }
        )
    return {"strategies": enabled, "max_requests_per_run": max_requests, "niches": out}
