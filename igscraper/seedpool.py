"""Seed pool: persist strong leads across runs to seed lookalike discovery.

A seed pool entry is a username that scored highly (and qualified) in a past
run. Feeding these back into the ``chaining`` strategy lets coverage compound:
each run discovers lookalikes of the best accounts found so far.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("igscraper.seedpool")


def load(state_path: str | Path) -> Dict[str, List[str]]:
    """Load {niche_name: [username, ...]}; missing/corrupt file -> {}."""
    path = Path(state_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as exc:  # noqa: BLE001
        logger.warning("Could not read seed pool %s (%s); starting empty.", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): [str(u) for u in v if str(u).strip()]
        for k, v in data.items()
        if isinstance(v, list)
    }


def save(
    state_path: str | Path,
    rows: List[Dict],
    per_niche: int,
    min_score: float,
) -> Dict[str, List[str]]:
    """Merge this run's strong qualifying leads into the pool, newest wins.

    Returns the written pool. Only rows that ``qualify`` and meet ``min_score``
    become seeds, ranked by score, capped at ``per_niche`` per niche.
    """
    path = Path(state_path)
    pool = load(path)

    # Best score per (niche, username) among this run's strong rows.
    for niche_name in {n for r in rows for n in (r.get("niches") or [])}:
        best: Dict[str, float] = {}
        for row in rows:
            if niche_name not in (row.get("niches") or []):
                continue
            if not row.get("qualifies"):
                continue
            score = float(row.get("score") or 0)
            if score < float(min_score):
                continue
            username = row.get("username") or ""
            if username:
                best[username] = max(best.get(username, 0.0), score)

        existing = pool.get(niche_name, [])
        ordered: List[str] = []
        seen: set[str] = set()
        # This run's best first (highest score), then previously pooled seeds.
        for username, _ in sorted(best.items(), key=lambda kv: kv[1], reverse=True):
            if username not in seen:
                seen.add(username)
                ordered.append(username)
        for username in existing:
            if username not in seen:
                seen.add(username)
                ordered.append(username)
        pool[niche_name] = ordered[: int(per_niche)] if per_niche else ordered

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pool, indent=2, sort_keys=True))
        logger.info("Seed pool updated: %s", path)
    except OSError as exc:  # noqa: BLE001
        logger.warning("Could not write seed pool %s: %s", path, exc)
    return pool
