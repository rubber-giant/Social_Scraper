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

from igscraper.client import InstagramClient, MissingCredentialsError  # noqa: E402
from igscraper.config import load_config  # noqa: E402
from igscraper.discovery import discover  # noqa: E402
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

    if not cfg.niches or not any(n.name for n in cfg.niches):
        log.error("No named niches found in config. Add at least one under 'niches:'.")
        return 1

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
        authors_by_niche, niches_by_author, found_tag_by_author = discover(cl, cfg)

        if not authors_by_niche or not any(authors_by_niche.values()):
            log.info("No candidates found. Try more hashtags, another niche, or 'top' mode.")
            return 0

        log.info("== Enrichment ==")
        rows = enrich(cl, cfg, authors_by_niche, niches_by_author, found_tag_by_author)

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
