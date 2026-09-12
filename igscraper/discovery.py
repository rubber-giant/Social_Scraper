"""Discovery: turn a niche keyword into candidate brand usernames.

Strategy: query the niche's hashtags (the niche slug plus any user-supplied
tags), scan the post authors, and de-duplicate. Because authors are pulled
from live posts in the tag feed, the resulting candidates are accounts that
are actually posting in the niche right now.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Set, Tuple

from .client import InstagramClient, pick_authors_from_media
from .config import Config, Niche

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


def discover(
    cl: InstagramClient,
    config: Config,
) -> Tuple[Dict[str, List[str]], Dict[str, Set[str]], Dict[str, str]]:
    """Discover candidate usernames per niche.

    Returns (authors_by_niche, niches_by_author, found_tag_by_author).
    niches_by_author tracks which niches each author matched, and
    found_tag_by_author records the hashtag that surfaced each author first.
    """
    settings = config.settings
    mode = str(settings.get("hashtag_mode", "recent"))
    per_tag = int(settings.get("hashtag_medias_per_tag", 30))

    authors_by_niche: Dict[str, List[str]] = {}
    niches_by_author: Dict[str, Set[str]] = {}
    found_tag_by_author: Dict[str, str] = {}

    for niche in config.niches:
        if not niche.name:
            continue
        tags = niche_hashtags(niche)
        authors: List[str] = []
        known: Set[str] = set()
        for tag in tags:
            if niche.max_authors and len(authors) >= niche.max_authors:
                break
            medias = cl.hashtag_medias(tag, per_tag, mode)
            tag_authors = pick_authors_from_media(medias)
            fresh = [a for a in tag_authors if a not in known]
            for a in fresh:
                authors.append(a)
                known.add(a)
                found_tag_by_author.setdefault(a, tag)
            logger.info(
                "  #%s: %d posts scanned -> %d new authors (total %d)",
                tag,
                len(medias),
                len(fresh),
                len(authors),
            )
            if niche.max_authors and len(authors) >= niche.max_authors:
                break

        authors = authors[: niche.max_authors] if niche.max_authors else authors
        authors_by_niche[niche.name] = authors
        for author in authors:
            niches_by_author.setdefault(author, set()).add(niche.name)
        logger.info(
            "Niche '%s' -> %d candidate authors (tags: %s)",
            niche.name,
            len(authors),
            ", ".join("#" + t for t in tags),
        )

    return authors_by_niche, niches_by_author, found_tag_by_author
