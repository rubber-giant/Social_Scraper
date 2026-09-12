"""Enrichment: fetch full profiles + recent activity for discovered candidates."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .client import InstagramClient
from .config import Config

logger = logging.getLogger("igscraper.enrich")


def _dedupe_order(authors_by_niche: Dict[str, List[str]]) -> List[str]:
    """Flatten per-niche author lists to a de-duplicated, stable order."""
    seen: Set[str] = set()
    ordered: List[str] = []
    for authors in authors_by_niche.values():
        for author in authors:
            if author not in seen:
                seen.add(author)
                ordered.append(author)
    return ordered


def enrich(
    cl: InstagramClient,
    config: Config,
    authors_by_niche: Dict[str, List[str]],
    niches_by_author: Dict[str, Set[str]],
    found_tag_by_author: Dict[str, str],
) -> List[Dict]:
    """Fetch and enrich profiles for all discovered candidates.

    Each returned row is a flat dict of the profile plus:
      niches       -> list of matched niche names
      found_via    -> hashtag that first surfaced the account
      latest_post  -> datetime of the newest sampled post (or None)
      sample_count, avg_likes, avg_comments, eng_pct
    """
    usernames = _dedupe_order(authors_by_niche)
    cap = int(config.settings.get("max_candidates", 0))
    if cap and len(usernames) > cap:
        logger.warning(
            "Truncating candidate list from %d to max_candidates=%d", len(usernames), cap
        )
        usernames = usernames[:cap]

    sample_posts = int(config.scoring.get("engagement_sample_posts", 0))
    # Always pull at least the newest post so we can measure activity/recency.
    media_amount = max(1, sample_posts)

    rows: List[Dict] = []
    logger.info("Enriching %d candidate profiles ...", len(usernames))
    for i, username in enumerate(usernames, 1):
        profile = cl.profile(username)
        if profile is None:
            continue  # fetch failure already logged by client

        row = dict(profile)
        row["username"] = username
        row["niches"] = sorted(niches_by_author.get(username, set()))
        row["found_via"] = found_tag_by_author.get(username, "")

        # --- recent activity (recency + engagement sample) ---
        row["latest_post"] = None
        row["sample_count"] = 0
        row["avg_likes"] = 0
        row["avg_comments"] = 0
        row["eng_pct"] = None

        user_id = profile["pk"]
        if profile["media_count"] and user_id:
            media = cl.recent_media(user_id, media_amount)
            media = [m for m in media if m is not None]
            if media:
                row["sample_count"] = len(media)
                row["latest_post"] = max(m.taken_at for m in media)
                row["avg_likes"] = round(
                    sum(int(m.like_count or 0) for m in media) / len(media), 1
                )
                row["avg_comments"] = round(
                    sum(int(m.comment_count or 0) for m in media) / len(media), 1
                )
                followers = int(profile["follower_count"] or 0)
                if followers:
                    row["eng_pct"] = round(
                        (row["avg_likes"] + row["avg_comments"]) / followers * 100, 2
                    )

        rows.append(row)
        if i % 10 == 0 or i == len(usernames):
            logger.info("  enriched %d/%d", i, len(usernames))

    logger.info("Enriched %d of %d candidates.", len(rows), len(usernames))
    return rows


def latest_post_age_days(row: Dict) -> Optional[int]:
    """Days between the newest post and now; None if there is no post."""
    latest = row.get("latest_post")
    if latest is None:
        return None
    delta = datetime.now(timezone.utc) - latest
    return max(0, int(delta.total_seconds() // 86400))
