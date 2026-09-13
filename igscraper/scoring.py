"""Scoring & filtering: decide which scraped accounts qualify as leads.

Pure functions (no network). Given an enriched profile row, they compute
transparent signal flags, a 0-100 score, and whether the account passes the
hard gates (sells product + active + right size + contact reachable).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .config import Config
from .enrich import latest_post_age_days

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Category values that indicate a personal creator / media page rather than a
# business selling products. Used to keep "is_business + category" from falsely
# flagging creators. Substring match on the category name.
CREATOR_CATEGORY_HINTS = (
    "creator",
    "blog",
    "artist",
    "musician",
    "writer",
    "author",
    "photographer",
    "public figure",
    "actor",
    "influencer",
    "performer",
    "entertain",
    "podcast",
    "news",
    "media",
    "coach",
    "community",
    "just for fun",
)


def _is_creator_category(category: str) -> bool:
    category = (category or "").lower()
    return any(hint in category for hint in CREATOR_CATEGORY_HINTS)


def extract_emails(text: str) -> List[str]:
    """All email addresses found in a string, de-duplicated, lower-cased."""
    if not text:
        return []
    seen: List[str] = []
    for m in EMAIL_RE.findall(text):
        email = m.lower()
        if email not in seen:
            seen.append(email)
    return seen


def _has_commerce_keyword(name: str, bio: str, keywords: List[str]) -> Optional[str]:
    blob = f"{name} {bio}".lower()
    for kw in keywords:
        if kw.lower() in blob:
            return kw
    return None


def evaluate(row: Dict, config: Config) -> Dict:
    """Annotate an enriched profile row with scoring/filtering fields."""
    bio = row.get("biography") or ""
    name = row.get("full_name") or ""
    username = row.get("username") or ""
    followers = int(row.get("follower_count") or 0)
    is_business = bool(row.get("is_business"))
    category = (row.get("category") or "").strip()
    external_url = (row.get("external_url") or "").strip()
    public_email = (row.get("public_email") or "").strip()
    public_phone = (row.get("public_phone") or "").strip()

    # -- product signal -------------------------------------------------
    # Require evidence of *selling*, not just being a professional account:
    # a link-in-bio, a commerce keyword, or a business category that is not a
    # creator/media category.
    commerce_kw = _has_commerce_keyword(name, bio, config.commerce_keywords)
    creator_category = _is_creator_category(category)
    product_detail: List[str] = []
    if external_url:
        product_detail.append("link-in-bio")
    if commerce_kw:
        product_detail.append(f"kw:'{commerce_kw}'")
    if is_business and category and not creator_category:
        product_detail.append("business-category")
    row["product_signal"] = bool(product_detail)
    row["product_detail"] = ", ".join(product_detail)

    # -- contact ---------------------------------------------------------
    bio_emails = extract_emails(bio)
    all_emails = list(dict.fromkeys([e for e in [public_email] + bio_emails if e]))
    primary_email = all_emails[0] if all_emails else ""
    alt_emails = all_emails[1:]
    row["email"] = primary_email
    row["email_alt"] = "; ".join(alt_emails[:3])
    row["phone"] = public_phone
    row["website"] = external_url
    has_contact = bool(all_emails or public_phone or external_url)

    # -- activity / recency ----------------------------------------------
    days = latest_post_age_days(row)
    row["days_since_post"] = days
    row["active"] = days is not None and days <= int(
        config.scoring.get("max_days_since_last_post", 30)
    )

    # -- score (0-100) -----------------------------------------------------
    f = followers
    if 2_000 <= f <= 100_000:
        size_pts = 25
    elif f < 2_000:
        size_pts = 18 if f >= 1_500 else 12
    elif f <= 200_000:
        size_pts = 22
    elif f <= 300_000:
        size_pts = 16
    else:
        size_pts = 10

    if days is None:
        recency_pts = 0
    elif days <= 7:
        recency_pts = 25
    elif days <= 14:
        recency_pts = 20
    elif days <= 21:
        recency_pts = 14
    else:
        recency_pts = 7

    if external_url and commerce_kw:
        product_pts = 25
    elif external_url:
        product_pts = 22
    elif commerce_kw:
        product_pts = 18
    elif is_business and category and not creator_category:
        product_pts = 15
    else:
        product_pts = 0

    if primary_email:
        contact_pts = 25
    elif public_phone:
        contact_pts = 18
    elif external_url:
        contact_pts = 14
    else:
        contact_pts = 0

    row["score"] = round(size_pts + recency_pts + product_pts + contact_pts)

    # Optional provenance bonus: reward higher-quality discovery sources
    # (chaining=2.0 > keyword=1.5 > hashtag=1.0). 0 disables it entirely.
    bonus_cfg = float(config.discovery.get("provenance_bonus", 0) or 0)
    if bonus_cfg > 0:
        weight = float(row.get("discovery_weight") or 0)
        row["score"] = round(row["score"] + min(bonus_cfg, bonus_cfg * weight / 2.0))

    # -- hard gates ----------------------------------------------------------
    sc = config.scoring
    max_days = int(sc.get("max_days_since_last_post", 30))
    gates: List[str] = []
    if not row["product_signal"]:
        gates.append("no-product-signal")
    if not row["active"]:
        gates.append("inactive")
    if not (int(sc.get("min_followers", 0)) <= f <= int(sc.get("max_followers", 0))):
        gates.append("size-out-of-range")
    if not has_contact:
        gates.append("no-contact")

    min_eng = float(sc.get("min_engagement_pct", 0.0))
    if min_eng > 0:
        eng = row.get("eng_pct")
        if eng is None:
            gates.append("engagement-unmeasured")
        elif eng < min_eng:
            gates.append("low-engagement")

    # Niche-relevance check defaults to flag-only (never drops a lead); a gate
    # is only added when the user opts into action: drop.
    rel = config.discovery.get("relevance", {}) or {}
    if rel.get("enabled") and rel.get("action") == "drop" and row.get("relevance_flagged"):
        gates.append("niche-mismatch")

    row["qualifies"] = not gates
    row["flags"] = "|".join(gates)
    return row
