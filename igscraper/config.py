"""Load configuration (YAML) and secrets (.env) for the scraper."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "settings": {
        "per_request_delay_sec": 3.0,
        "request_delay_jitter": 2.0,
        # instagrapi sleeps request_timeout before EVERY non-login request, so
        # this dominates per-request pacing (~= request_timeout + delay_range).
        # It's also the socket timeout: too low and slow replies raise
        # ClientRequestTimeout (which retries after a 60 s sleep).
        "request_timeout": 30,
        "hashtag_mode": "recent",  # top | recent | both
        "hashtag_medias_per_tag": 30,
        "max_candidates": 400,
    },
    "scoring": {
        "min_followers": 1000,
        "max_followers": 500000,
        "max_days_since_last_post": 30,
        "min_engagement_pct": 0.0,
        "engagement_sample_posts": 0,
    },
    "commerce_keywords": [
        "shop",
        "store",
        "free shipping",
        "etsy",
        "boutique",
        "order",
        "buy",
    ],
    "discovery": {
        # Strategies that contribute candidates. Each is inert unless its
        # per-niche input exists (seeds / keyword_queries).
        "enabled": ["hashtag", "keyword", "chaining"],
        # Hard cap on Instagram requests per run (0 = unlimited). Bounds runtime.
        "max_requests_per_run": 400,
        # Candidates each strategy may add per niche (0 = unlimited).
        "per_strategy_max": {
            "hashtag": 200,
            "keyword": 60,
            "chaining": 100,
        },
        # Provenance priority: higher weight survives the per-niche cap first.
        "source_weights": {
            "chaining": 2.0,
            "keyword": 1.5,
            "hashtag": 1.0,
        },
        # Cap each strategy's share of a niche's max_authors (fraction), so the
        # heaviest source can't starve the others. Leftover slots are backfilled.
        "source_share": {
            "chaining": 0.5,
        },
        # Optional score bonus by provenance (0 = score math untouched).
        "provenance_bonus": 0,
        "hashtag": {
            # Falls back to settings.hashtag_mode / settings.hashtag_medias_per_tag.
            "mode": None,
            "medias_per_tag": None,
        },
        "keyword": {
            "per_query": 30,
            "max_queries_per_niche": 4,
        },
        "chaining": {
            "per_seed": 12,
            "max_seeds_per_niche": 8,
            # Strong keyword hits reused as seeds in the same run.
            "max_seeds_from_keyword": 3,
            # Fall back to the public GraphQL related-profiles query.
            "fallback_gql": True,
        },
        "seed_pool": {
            "enabled": True,
            "state_path": "output/seed_pool.json",
            "per_niche": 10,
            "min_score": 70,
        },
        "relevance": {
            "enabled": True,
            "sample_posts": 3,
            "min_overlap": 1,
            "action": "flag",  # flag | drop
        },
    },
    "niches": [{"name": "skincare", "hashtags": [], "max_authors": 200}],
}


@dataclass
class Niche:
    name: str
    hashtags: List[str] = field(default_factory=list)
    max_authors: int = 200
    seeds: List[str] = field(default_factory=list)
    keyword_queries: List[str] = field(default_factory=list)
    relevance_keywords: List[str] = field(default_factory=list)


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Typed access to merged YAML config + environment variables."""

    def __init__(self, raw: dict, env: dict | None = None):
        env = env or os.environ
        self.settings: dict = raw["settings"]
        self.scoring: dict = raw["scoring"]
        self.discovery: dict = raw["discovery"]
        self.commerce_keywords: List[str] = raw["commerce_keywords"]
        self.niches: List[Niche] = [
            Niche(
                name=str(n.get("name", "").strip()),
                hashtags=[
                    str(h).strip().lstrip("#") for h in n.get("hashtags", []) or []
                ],
                max_authors=int(n.get("max_authors", 200)),
                seeds=[
                    str(s).strip().lstrip("@")
                    for s in n.get("seeds", []) or []
                    if str(s).strip()
                ],
                keyword_queries=[
                    str(q).strip()
                    for q in n.get("keyword_queries", []) or []
                    if str(q).strip()
                ],
                relevance_keywords=[
                    str(k).strip().lower().lstrip("#")
                    for k in n.get("relevance_keywords", []) or []
                    if str(k).strip()
                ],
            )
            for n in raw["niches"]
        ]
        self.session_path: Path = PROJECT_ROOT / "session.json"
        self.env_path: Path = PROJECT_ROOT / ".env"
        self.username: str = env.get("INSTAGRAM_USERNAME", "").strip()
        self.password: str = env.get("INSTAGRAM_PASSWORD", "").strip()


def load_config(config_path: str | Path | None = None) -> Config:
    config_path = Path(config_path) if config_path else PROJECT_ROOT / "config.yaml"

    if config_path.exists():
        raw = _deep_merge(DEFAULTS, yaml.safe_load(config_path.read_text()) or {})
    else:
        raw = dict(DEFAULTS)
        # Avoid mutating shared defaults across calls
        import copy

        raw = copy.deepcopy(raw)

    # .env in project root, then .env in cwd as fallback
    for dotenv_path in (PROJECT_ROOT / ".env", Path.cwd() / ".env"):
        if dotenv_path.exists():
            load_dotenv(dotenv_path)
            break

    return Config(raw)
