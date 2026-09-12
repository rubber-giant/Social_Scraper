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
    "niches": [{"name": "skincare", "hashtags": [], "max_authors": 200}],
}


@dataclass
class Niche:
    name: str
    hashtags: List[str] = field(default_factory=list)
    max_authors: int = 200


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
        self.commerce_keywords: List[str] = raw["commerce_keywords"]
        self.niches: List[Niche] = [
            Niche(
                name=str(n.get("name", "").strip()),
                hashtags=[str(h).strip().lstrip("#") for h in n.get("hashtags", [])],
                max_authors=int(n.get("max_authors", 200)),
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
