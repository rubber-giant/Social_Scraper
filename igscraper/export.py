"""Excel export: build a workbook from scored lead rows."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

logger = logging.getLogger("igscraper.export")

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
LINK_FONT = Font(color="0563C1", underline="single")
WRAP = Alignment(vertical="top", wrap_text=True)
TOP = Alignment(vertical="top")

# (sheet header, row key, kind) — kinds control rendering/hyperlinks.
COLUMNS: Sequence[tuple] = [
    ("Score", "score", "int"),
    ("Brand name", "full_name", "text"),
    ("Handle", "handle", "handle"),
    ("Bio", "biography", "text"),
    ("Category", "category", "text"),
    ("Followers", "follower_count", "int"),
    ("Following", "following_count", "int"),
    ("Posts", "media_count", "int"),
    ("Avg likes", "avg_likes", "num"),
    ("Avg comments", "avg_comments", "num"),
    ("Eng rate %", "eng_pct", "pct"),
    ("Latest post", "latest_date", "text"),
    ("Days inactive", "days_since_post", "int_or_blank"),
    ("Active?", "active", "yesno"),
    ("Business?", "is_business", "yesno"),
    ("Verified?", "is_verified", "yesno"),
    ("Website", "website", "website"),
    ("Email", "email", "text"),
    ("Other emails", "email_alt", "text"),
    ("Phone", "phone", "text"),
    ("Product signals", "product_detail", "text"),
    ("Matched niche", "niche_label", "text"),
    ("Found via", "found_via_label", "text"),
    ("Discovery sources", "discovery_sources_label", "text"),
    ("Relevance", "relevance_matched", "text"),
    ("Why excluded", "flags", "text"),
]

WIDTHS = {
    "Score": 7, "Brand name": 22, "Handle": 24, "Bio": 55, "Category": 18,
    "Followers": 10, "Following": 10, "Posts": 8, "Avg likes": 9,
    "Avg comments": 12, "Eng rate %": 10, "Latest post": 12,
    "Days inactive": 12, "Active?": 8, "Business?": 10, "Verified?": 10,
    "Website": 32, "Email": 28, "Other emails": 28, "Phone": 15,
    "Product signals": 30, "Matched niche": 18, "Found via": 18,
    "Discovery sources": 40, "Relevance": 26,
    "Why excluded": 26,
}


def _finalize_row(row: Dict) -> Dict:
    """Add display-oriented fields derived from raw/scored values."""
    row = dict(row)
    row["handle"] = "@" + (row.get("username") or "")
    row["profile_url"] = f"https://www.instagram.com/{row.get('username') or ''}"
    latest = row.get("latest_post")
    row["latest_date"] = latest.strftime("%Y-%m-%d") if latest else ""
    row["niche_label"] = ", ".join(row.get("niches") or [])
    if not row.get("found_via_label"):
        row["found_via_label"] = "#" + row["found_via"] if row.get("found_via") else ""
    return row


def _write_row(ws, row: Dict, row_idx: int) -> None:
    for col_idx, (header, key, kind) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=row_idx, column=col_idx)
        value = row.get(key, "")

        if kind == "yesno":
            cell.value = "Yes" if value else "No"
        elif kind == "int":
            cell.value = int(value) if value not in (None, "") else None
        elif kind == "num":
            cell.value = value if isinstance(value, (int, float)) else None
        elif kind == "pct":
            cell.value = value if isinstance(value, (int, float)) else None
            if isinstance(cell.value, (int, float)):
                cell.number_format = '0.00"%"'
        elif kind == "int_or_blank":
            cell.value = int(value) if value not in (None, "") else None
        elif kind == "handle":
            cell.value = value
            if row.get("profile_url"):
                cell.hyperlink = row["profile_url"]
                cell.font = LINK_FONT
        elif kind == "website":
            cell.value = value or None
            if value:
                text = str(value)
                if text.startswith(("http://", "https://")):
                    cell.hyperlink = text
                else:
                    cell.hyperlink = "https://" + text
                cell.font = LINK_FONT
        else:  # text
            cell.value = value or None

        if kind in ("text", "handle", "website", "phone", "email", "bio"):
            cell.alignment = WRAP
        else:
            cell.alignment = TOP


def _add_sheet(wb: Workbook, title: str, rows: List[Dict]) -> None:
    ws = wb.create_sheet(title=title)
    # Header
    for col_idx, (header, _key, _kind) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = TOP
    # Body
    for r_idx, row in enumerate(rows, start=2):
        _write_row(ws, _finalize_row(row), r_idx)
    # Styling: freeze header, autofilter, widths, row heights
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"
    for col_idx, (header, _k, _kind) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = WIDTHS.get(header, 14)
    ws.row_dimensions[1].height = 20
    # Give bio/email columns room to breathe.
    for r_idx in range(2, len(rows) + 2):
        ws.row_dimensions[r_idx].height = 15
    logger.info("Wrote %d rows to sheet '%s'.", len(rows), title)


def export_workbook(rows: List[Dict], out_path: str | Path) -> Path:
    """Write all scored rows to an xlsx. Returns the output path."""
    leads = sorted(
        [r for r in rows if r.get("qualifies")], key=lambda r: r.get("score") or 0, reverse=True
    )
    others = sorted(
        [r for r in rows if not r.get("qualifies")], key=lambda r: r.get("score") or 0, reverse=True
    )

    wb = Workbook()
    wb.remove(wb.active)  # drop default sheet
    _add_sheet(wb, "Top Leads", leads)
    _add_sheet(wb, "All Candidates", leads + others)

    # Run-info / notes sheet
    ws = wb.create_sheet(title="Run Info")
    info = [
        ("Generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        ("Total candidates profiled", str(len(rows))),
        ("Top leads (qualify)", str(len(leads))),
        ("", ""),
        ("How scoring works", ""),
        ("Top Leads = sells product + active + in follower range + contact reachable.", ""),
        ("Score (0-100) ranks: size fit + post recency + product signals + contact quality.", ""),
        ("Product signals", "link-in-bio / commerce keyword in bio/name / business category."),
        ("Contact", "email in bio or public business email > phone > website (reach via site)."),
        ("", ""),
        ("How accounts were discovered", ""),
        ("'Discovery sources' lists every surface that found the account.", ""),
        ("hashtag = author of a post under a niche tag; keyword = account search;", ""),
        ("chaining = Instagram's 'similar accounts' expanded from seed brands.", ""),
        ("Higher-provenance sources (chaining > keyword > hashtag) rank first in each niche.", ""),
        ("'Relevance' shows the niche keywords actually matched in the account's own posts.", ""),
        ("", ""),
        ("Caveats", ""),
        ("- Data comes from Instagram's private API via instagrapi; use a throwaway account.", ""),
        ("- Public info only. Rate-limit delays are built in; still expect occasional blocks.", ""),
        ("- 'Why excluded' explains why an account missed the Top Leads sheet.", ""),
        ("- Manually verify before outreach: category/shop signals are heuristics.", ""),
    ]
    for r_idx, (label, value) in enumerate(info, start=1):
        a = ws.cell(row=r_idx, column=1, value=label)
        b = ws.cell(row=r_idx, column=2, value=value)
        a.font = Font(bold=label and not value)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 110

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
