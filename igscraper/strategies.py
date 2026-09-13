"""Pluggable discovery strategies.

Each strategy is a function ``(cl, config, niche, budget, ctx) -> List[Candidate]``
registered in :data:`STRATEGY_REGISTRY`. ``discovery.discover`` runs the enabled
ones safest/highest-yield first and merges the results.

Strategies:
  * hashtag  — authors of posts under the niche's tags (the original approach).
  * keyword  — accounts matching brand-intent search queries.
  * chaining — Instagram's "similar accounts" graph, expanded from seeds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .client import InstagramClient, pick_authors_from_media
from .config import Config, Niche
from .models import Candidate, Source

logger = logging.getLogger("igscraper.strategies")

# Run cheapest/safest & highest-yield first so the request budget is spent well.
SAFEST_FIRST = ["hashtag", "keyword", "chaining"]


@dataclass
class Budget:
    """Shared request budget across strategies (0 = unlimited)."""

    max_requests: int = 0
    used: int = 0
    per_strategy: Dict[str, int] = field(default_factory=dict)

    def request(self, strategy: str) -> bool:
        """Reserve one request; False if the hard cap is already reached."""
        if self.max_requests and self.used + 1 > self.max_requests:
            return False
        self.used += 1
        self.per_strategy[strategy] = self.per_strategy.get(strategy, 0) + 1
        return True


def _cfg(config: Config, section: str) -> dict:
    return config.discovery.get(section, {}) or {}


def _weight(config: Config, strategy: str) -> float:
    return float(config.discovery.get("source_weights", {}).get(strategy, 1.0))


def _cap(config: Config, strategy: str) -> int:
    return int(config.discovery.get("per_strategy_max", {}).get(strategy, 0))


def run_hashtag_strategy(
    cl: InstagramClient, config: Config, niche: Niche, budget: Budget, ctx: dict
) -> List[Candidate]:
    from .discovery import niche_hashtags  # lazy: avoids import cycle

    hs = _cfg(config, "hashtag")
    mode = str(hs.get("mode") or config.settings.get("hashtag_mode", "recent"))
    per_tag = int(
        hs.get("medias_per_tag") or config.settings.get("hashtag_medias_per_tag", 30)
    )
    cap = _cap(config, "hashtag")
    weight = _weight(config, "hashtag")

    out: List[Candidate] = []
    known: set[str] = set()
    for tag in niche_hashtags(niche):
        if cap and len(out) >= cap:
            break
        if not budget.request("hashtag"):
            logger.warning("Request budget exhausted during hashtag strategy.")
            break
        medias = cl.hashtag_medias(tag, per_tag, mode)
        authors = pick_authors_from_media(medias)
        fresh = 0
        for author in authors:
            if author in known:
                continue
            known.add(author)
            cand = Candidate(username=author)
            cand.add_source(Source("hashtag", tag, weight))
            out.append(cand)
            fresh += 1
            if cap and len(out) >= cap:
                break
        logger.info(
            "  #%s: %d posts -> %d new authors (niche total %d)",
            tag,
            len(medias),
            fresh,
            len(out),
        )
    return out


def run_keyword_strategy(
    cl: InstagramClient, config: Config, niche: Niche, budget: Budget, ctx: dict
) -> List[Candidate]:
    kw = _cfg(config, "keyword")
    per_query = int(kw.get("per_query", 30))
    max_queries = int(kw.get("max_queries_per_niche", 4))
    cap = _cap(config, "keyword")
    weight = _weight(config, "keyword")

    out: List[Candidate] = []
    known: set[str] = set()
    for query in niche.keyword_queries[:max_queries]:
        if cap and len(out) >= cap:
            break
        if not budget.request("keyword"):
            logger.warning("Request budget exhausted during keyword strategy.")
            break
        users = cl.search_users(query, per_query)
        fresh = 0
        for u in users:
            username = u["username"]
            if username in known:
                continue
            known.add(username)
            cand = Candidate(username=username, pk=u.get("pk") or None)
            cand.add_source(Source("keyword", query, weight))
            out.append(cand)
            fresh += 1
            if cap and len(out) >= cap:
                break
        logger.info(
            "  search '%s': %d users -> %d new (niche total %d)",
            query,
            len(users),
            fresh,
            len(out),
        )
    return out


def run_chaining_strategy(
    cl: InstagramClient, config: Config, niche: Niche, budget: Budget, ctx: dict
) -> List[Candidate]:
    ch = _cfg(config, "chaining")
    per_seed = int(ch.get("per_seed", 12))
    fallback_gql = bool(ch.get("fallback_gql", True))
    cap = _cap(config, "chaining")
    weight = _weight(config, "chaining")
    seeds: List[str] = ctx.get("seeds") or []

    out: List[Candidate] = []
    known: set[str] = set()
    for seed in seeds:
        if cap and len(out) >= cap:
            break
        # 1 request to resolve the seed's pk (also validates the account).
        if not budget.request("chaining"):
            logger.warning("Request budget exhausted during chaining strategy.")
            break
        prof = cl.profile(seed)
        pk = (prof or {}).get("pk")
        if not pk:
            logger.info("  seed @%s: could not resolve; skipped.", seed)
            continue

        if not budget.request("chaining"):
            logger.warning("Request budget exhausted during chaining strategy.")
            break
        users = cl.chaining(pk)
        if not users and fallback_gql:
            if not budget.request("chaining"):
                logger.warning("Request budget exhausted during chaining strategy.")
                break
            users = cl.related_profiles_gql(pk)

        fresh = 0
        for u in users[:per_seed]:
            username = u["username"]
            if username == seed or username in known:
                continue
            known.add(username)
            cand = Candidate(username=username, pk=u.get("pk") or None)
            cand.add_source(Source("chaining", f"@{seed}", weight))
            out.append(cand)
            fresh += 1
            if cap and len(out) >= cap:
                break
        logger.info(
            "  seed @%s: %d similar -> %d new (niche total %d)",
            seed,
            len(users),
            fresh,
            len(out),
        )
    return out


NICHE_STRATEGIES: Dict[str, Callable[..., List[Candidate]]] = {
    "hashtag": run_hashtag_strategy,
    "keyword": run_keyword_strategy,
    "chaining": run_chaining_strategy,
}


def build_seeds(
    config: Config,
    niche: Niche,
    pool_seeds: List[str],
    keyword_candidates: List[Candidate],
) -> List[str]:
    """Union of manual seeds, pooled seeds, and strong keyword hits (capped).

    Order is priority: manual -> pool -> same-run keyword hits.
    """
    ch = _cfg(config, "chaining")
    max_seeds = int(ch.get("max_seeds_per_niche", 8))
    max_kw = int(ch.get("max_seeds_from_keyword", 3))

    seeds: List[str] = []
    seen: set[str] = set()
    for username in list(niche.seeds) + list(pool_seeds):
        if username and username not in seen:
            seen.add(username)
            seeds.append(username)
    for cand in keyword_candidates[:max_kw]:
        if cand.username and cand.username not in seen:
            seen.add(cand.username)
            seeds.append(cand.username)
    return seeds[:max_seeds] if max_seeds else seeds
