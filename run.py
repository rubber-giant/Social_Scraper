"""Social Scraper — social-media lead scraper CLI entry point.

Usage:
    python run.py discover --config config.yaml --out output/leads.xlsx
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from igscraper import seedpool  # noqa: E402
from igscraper.client import (  # noqa: E402
    DEFAULT_REQUEST_TIMEOUT,
    InstagramClient,
    MissingCredentialsError,
)
from igscraper.config import PROJECT_ROOT, load_config  # noqa: E402
from igscraper.discovery import discover, plan  # noqa: E402
from igscraper.enrich import enrich  # noqa: E402
from igscraper.export import export_workbook  # noqa: E402
from igscraper.scoring import evaluate  # noqa: E402


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _fmt_duration(seconds: float) -> str:
    minutes = seconds / 60.0
    if minutes < 1:
        return f"{seconds:.0f} sec"
    if minutes < 120:
        return f"{minutes:.0f} min"
    return f"{minutes / 60.0:.1f} h"


def _print_plan(plan_data: dict, seconds_per_request: float) -> None:
    """Human-readable discovery plan for --dry-run (no network)."""
    strategies = plan_data.get("strategies") or []
    cap = plan_data.get("max_requests_per_run") or 0
    print("=" * 60)
    print("Discovery plan (dry run — no requests made)")
    print(f"Strategies: {', '.join(strategies) or '(none)'}")
    print(f"Request cap: {cap or 'unlimited'}")
    print("-" * 60)
    total = 0
    for entry in plan_data.get("niches", []):
        print(f"Niche: {entry['niche']}")
        for name, spec in entry["strategies"].items():
            refs = spec.get("refs") or []
            shown = ", ".join(refs[:8]) + (" ..." if len(refs) > 8 else "")
            print(f"  {name:<9} ~{spec['est_requests']:>3} req   {shown}")
        print(f"  {'subtotal':<9} ~{entry['est_requests']:>3} req")
        total += entry["est_requests"]
    print("-" * 60)
    print(f"Estimated discovery requests: ~{total}")
    print("  (enrichment then adds ~2 requests per discovered candidate)")
    print(
        f"Pacing: ~{seconds_per_request:.0f} s/request "
        "(instagrapi request_timeout sleep + delay_range)"
    )
    print(f"Estimated discovery wall time: ~{_fmt_duration(total * seconds_per_request)}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(prog="social-scraper", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_disc = sub.add_parser("discover", help="Discover + export leads")
    p_disc.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config YAML (default: config.yaml)",
    )
    p_disc.add_argument(
        "--out",
        default=None,
        help="Output .xlsx path (default: output/leads_<timestamp>.xlsx)",
    )
    p_disc.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated override of discovery.enabled (e.g. hashtag,keyword)",
    )
    p_disc.add_argument(
        "--only-niche",
        default=None,
        help="Comma-separated niche name(s) to run, ignoring the rest",
    )
    p_disc.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the discovery plan + request estimate and exit (no login)",
    )
    p_disc.add_argument(
        "-v", "--verbose", action="store_true", help="Debug logging"
    )
    args = parser.parse_args()

    setup_logging(getattr(args, "verbose", False))
    log = logging.getLogger("run")

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not load config: %s", exc)
        return 1

    # -- optional filters --------------------------------------------------
    if args.only_niche:
        wanted = {n.strip().lower() for n in args.only_niche.split(",") if n.strip()}
        cfg.niches = [n for n in cfg.niches if n.name.lower() in wanted]
    if args.strategies is not None:
        cfg.discovery["enabled"] = [
            s.strip() for s in args.strategies.split(",") if s.strip()
        ]

    if not cfg.niches or not any(n.name for n in cfg.niches):
        log.error("No named niches found in config. Add at least one under 'niches:'.")
        return 1

    # -- seed pool (carried over from prior runs) --------------------------
    pool_cfg = cfg.discovery.get("seed_pool", {}) or {}
    pool_enabled = bool(pool_cfg.get("enabled", True))
    pool_path = PROJECT_ROOT / str(pool_cfg.get("state_path", "output/seed_pool.json"))
    seed_pool = seedpool.load(pool_path) if pool_enabled else {}

    if args.dry_run:
        base = float(cfg.settings.get("per_request_delay_sec", 3.0))
        jitter = float(cfg.settings.get("request_delay_jitter", 2.0))
        timeout = float(cfg.settings.get("request_timeout", DEFAULT_REQUEST_TIMEOUT))
        _print_plan(plan(cfg, seed_pool), timeout + base + jitter / 2.0)
        return 0

    has_sessionid = bool(os.environ.get("INSTAGRAM_SESSIONID", "").strip())
    if not (has_sessionid or (cfg.username and cfg.password)):
        log.error("No login configured.")
        log.error(
            "Copy .env.example to .env, then either:\n"
            "  1. INSTAGRAM_SESSIONID=<value>  (fastest for new accounts; no password)\n"
            "  2. INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD  (use a throwaway account)"
        )
        return 1

    out_path = args.out or (
        f"output/leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    try:
        cl = InstagramClient(cfg)
        cl.login()

        log.info("== Discovery ==")
        result = discover(cl, cfg, seed_pool)

        if not result.candidates:
            log.info("No candidates found. Try more hashtags/seeds/queries or 'top' mode.")
            return 0

        log.info("== Enrichment ==")
        authors_by_niche, niches_by_author, found_tag_by_author = result.to_legacy()
        rows = enrich(
            cl,
            cfg,
            authors_by_niche,
            niches_by_author,
            found_tag_by_author,
            candidates=result.candidates,
        )

        if not rows:
            log.info("No profiles could be fetched for the discovered accounts.")
            return 0

        log.info("== Scoring ==")
        rows = [evaluate(r, cfg) for r in rows]
        leads = [r for r in rows if r.get("qualifies")]
        log.info(
            "Scored %d accounts -> %d qualifying leads.",
            len(rows),
            len(leads),
        )

        if pool_enabled:
            seedpool.save(
                pool_path,
                rows,
                per_niche=int(pool_cfg.get("per_niche", 10)),
                min_score=float(pool_cfg.get("min_score", 70)),
            )

        path = export_workbook(rows, out_path)
    except MissingCredentialsError as exc:
        log.error(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        log.exception("Run failed: %s", exc)
        return 1

    print("\n" + "=" * 60)
    print(f"Done. {len(leads)} qualifying leads from {len(rows)} candidates.")
    print(f"Workbook: {path.resolve()}")
    print("  Sheet 'Top Leads'      -> accounts that passed the filters (scored)")
    print("  Sheet 'All Candidates' -> everything discovered, with exclusion reasons")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
