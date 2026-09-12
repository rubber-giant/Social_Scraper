# Social Scraper

A social media scraper that takes a list of product **niches** you define in
`config.yaml` and scrapes accounts for them — collecting public profile data,
filtering for active accounts that look like product sellers with reachable
contact info, scoring each one, and exporting the results to a spreadsheet.

Currently targets **Instagram** public data. Point it at niches like candles,
skincare, or pet accessories; it discovers matching accounts, enriches their
profiles, and writes an `.xlsx` you can work straight from.

---

## Table of contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Login setup](#login-setup)
- [Running it](#running-it)
- [What you get (output)](#what-you-get-output)
- [Tuning runtime & lead volume](#tuning-runtime--lead-volume)
- [Adding niches optimally](#adding-niches-optimally)
- [Config reference](#config-reference)
- [Troubleshooting](#troubleshooting)
- [Sharing this repo safely (security & privacy)](#sharing-this-repo-safely-security--privacy)
- [Project structure](#project-structure)

---

## How it works

1. **Discover** — for each niche, scans the niche's hashtag feed(s) and collects
   the accounts posting there right now (de-duplicated across niches).
2. **Enrich** — pulls each candidate's public profile (bio, category, followers,
   business email/phone, link-in-bio) plus their latest post (for activity).
3. **Score & filter** — a lead qualifies only if it:
   - looks like it **sells a product** (link-in-bio, commerce keyword in
     bio/name, or a non-creator business category), **and**
   - is **active** (posted within `max_days_since_last_post`), **and**
   - is inside your **follower range**, **and**
   - is **contactable** (email / public business email / phone / website).
   Each qualifying account also gets a 0–100 score (size fit + recency +
   product signal + contact quality).
4. **Export** — a styled `.xlsx` with clickable handles/websites, a `Top Leads`
   sheet, an `All Candidates` sheet (with exclusion reasons), and a `Run Info`
   sheet.

---

## Requirements

- **Python 3.10–3.12** (recommended). `instagrapi` and its deps may not support
  3.13/3.14 yet — if `pip install` fails, use 3.11 or 3.12.
- An Instagram account (see [Login setup](#login-setup)). **Use a throwaway /
  spare account, not your main.**
- Linux/macOS (Windows works with the equivalent venv paths).

---

## Quick start

```bash
# 1. go to the project
cd Social_Scraper

# 2. create an isolated virtual environment and install deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip

# 3. create your config + secrets from the examples
cp config.example.yaml config.yaml               # Windows: copy
cp .env.example .env

# 4. edit config.yaml (your niches + limits) and .env (login) — see below

# 5. run
.venv/bin/python run.py discover
```

Nothing is installed globally; everything lives in `.venv/` inside the project.

---

## Login setup

Brand-new Instagram accounts get challenged almost every time they log in from a
server. Pick whichever mode fits your account — the tool tries **sessionid
first**, then falls back to username/password.

### Option A — `sessionid` (recommended, especially for new accounts)

Reuses a session you already have in a browser, so there's no password login and
no checkpoint.

1. Log into **instagram.com** in your browser as the account you'll use.
2. Open DevTools (`F12`) → **Application** (Chrome/Edge) or **Storage**
   (Firefox) → **Cookies** → `https://www.instagram.com`.
3. Copy the value of the **`sessionid`** cookie (it's long and starts with a
   number).
4. Put it in `.env`:

   ```ini
   INSTAGRAM_SESSIONID=1234567890%3AabcDEF...your_cookie_value
   ```

### Option B — username / password

Works best with an account that has existed a while and is used normally in the
app (an older spare account is ideal).

```ini
INSTAGRAM_USERNAME=your_throwaway_username
INSTAGRAM_PASSWORD=your_throwaway_password
#INSTAGRAM_2FA_CODE=123456        # only if 2FA is on; better to turn 2FA off
```

On first successful login the tool saves `session.json` (gitignored) and reuses
it on later runs, so you won't re-login every time.

---

## Running it

```bash
# uses ./config.yaml, writes to output/leads_<timestamp>.xlsx
.venv/bin/python run.py discover

# custom config and output path
.venv/bin/python run.py discover --config config.yaml --out output/leads.xlsx

# more detail in the logs
.venv/bin/python run.py discover -v
```

Long runs are fine in the background:

```bash
nohup .venv/bin/python run.py discover > run.log 2>&1 &
```

---

## What you get (output)

`output/leads_<timestamp>.xlsx` with three sheets:

- **Top Leads** — accounts that passed every gate, sorted by score. This is your
  shortlist.
- **All Candidates** — everything discovered, including a `Why excluded` column
  (`inactive`, `no-contact`, `size-out-of-range`, `no-product-signal`, ...).
- **Run Info** — timestamp, counts, and how the scoring works.

Key columns: `Score`, `Brand name`, `Handle` (clickable), `Bio`, `Category`,
`Followers`, `Avg likes`, `Eng rate %`, `Latest post`, `Days inactive`,
`Active?`, `Website` (clickable), `Email`, `Other emails`, `Phone`,
`Product signals`, `Matched niche`, `Found via`, `Why excluded`.

---

## Tuning runtime & lead volume

Two things decide how long a run takes and how many leads you get: **how many
candidates** you collect, and **how long each candidate takes**.

**Rules of thumb** (default pacing of 3–5 s per request, ~2 requests per
candidate):

- **Time ≈ candidates × ~1 minute.**
- **Leads ≈ 15–20% of candidates.**

**Measured example** (this project, default settings): `#jwellery` + `#tshirts`
niches → **150 candidates → 27 leads**, and the run took **~3 hours**. So:

| Candidates | Approx time | Approx leads |
|-----------:|------------:|-------------:|
| 20         | ~20 min     | 3–4          |
| 50         | ~50 min     | 8–10         |
| 150        | ~3 h        | ~27 (measured) |
| 400        | ~7–8 h      | 60–80        |

> Times are dominated by request pacing, not your CPU. Lowering delays speeds
> runs up but raises the chance Instagram throttles or flags the account.

### Which knobs to turn

| Knob | Where | Effect on time | Effect on leads |
|---|---|---|---|
| `per_request_delay_sec` / `request_delay_jitter` | `settings` | ↓ = faster, more risk | none |
| `hashtag_medias_per_tag` | `settings` | ↑ = more candidates = more time | ↑ |
| `hashtag_mode` (`top`/`recent`/`both`) | `settings` | `both` ≈ 2× discovery | ↑ |
| `niches[].max_authors` | per niche | caps that niche's candidates | caps it |
| `max_candidates` | `settings` | hard cap on total enriched | caps total |
| `engagement_sample_posts` | `scoring` | `>0` = more requests per candidate | enables engagement gate |
| `scoring.*` gates | `scoring` | free (filtering) | ↑/↓ |

### Example presets

**Quick test** — sanity-check your setup in ~5 minutes, ~3–5 leads:

```yaml
settings:
  hashtag_mode: recent
  hashtag_medias_per_tag: 10
  max_candidates: 30
scoring:
  engagement_sample_posts: 0
niches:
  - name: candles
    hashtags: [smallbizcandles]
    max_authors: 30
```

**Balanced** — about an hour, ~10–15 leads:

```yaml
settings:
  hashtag_mode: recent
  hashtag_medias_per_tag: 30
  max_candidates: 60
niches:
  - name: candles
    hashtags: [candlebrand, smallbizcandles]
    max_authors: 40
  - name: pet accessories
    hashtags: [petaccessoriesbrand]
    max_authors: 40
```

**Big run** — leave it overnight, ~50+ leads:

```yaml
settings:
  hashtag_mode: both
  hashtag_medias_per_tag: 80
  max_candidates: 400
niches:
  - name: candles
    hashtags: [candlebrand, smallbizcandles, handmadecandles]
    max_authors: 120
  - name: pet accessories
    hashtags: [petaccessoriesbrand, smallbizpets]
    max_authors: 120
  - name: home decor
    hashtags: [homedecorstore]
    max_authors: 120
```

**Scale-to-fit tip:** keep the **sum of `max_authors` ≤ `max_candidates`**, or
the global cap will silently truncate the niches listed last.

---

## Adding niches optimally

A niche is just a keyword plus a few hashtags. The name is auto-slugged into a
hashtag (`home decor` → `#homedecor`), and `hashtags[]` adds **extra** tags.

**Do:**

- Use a **short product category you'd actually film** (`candles`, `skincare`,
  `pet accessories`, `activewear`).
- Pick **specific, product-intent tags** — they surface brands, not random
  people: `#candlebrand`, `#smallbizcandles`, `#handmadecandles`.
- Keep **2–4 tags per niche**. More tags ≈ linearly more discovery time.
- **Order niches by priority.** Enrichment follows config order and
  `max_candidates` truncates from the top, so put your best niches first.
- Budget each niche with `max_authors`.

**Avoid:**

- **Mega-broad tags** like `#gifts`, `#fyp`, `#viral`, `#love` — they pull in
  tons of unrelated personal accounts, so you pay the runtime cost and filter
  them all out.
- **Too many niches at once** — each one multiplies discovery time and candidate
  count.

**Good vs. not-so-good example:**

```yaml
niches:
  # GOOD: specific, product-intent tags, sensible cost caps
  - name: candles
    hashtags: [candlebrand, smallbizcandles, handmadecandles]
    max_authors: 60
  - name: pet accessories
    hashtags: [petaccessoriesbrand, smallbizpets]
    max_authors: 50

  # AVOID: vague mega-tags sweep in random personal accounts -> slow + noisy
  - name: gifts
    hashtags: [gifts, fyp, viral, love]
    max_authors: 500
```

**Adding a third niche** is as simple as appending to the list:

```yaml
  - name: activewear
    hashtags: [activewearbrand, smallbizactivewear]
    max_authors: 50
```

Then re-run — niches are independent and de-duplicated, so overlapping accounts
only get enriched once.

---

## Config reference

`config.yaml` mirrors `config.example.yaml`; every key is optional.

| Key | Default | Meaning |
|---|---|---|
| `settings.per_request_delay_sec` | `3.0` | Base seconds between requests. |
| `settings.request_delay_jitter` | `2.0` | Random extra seconds added per request. |
| `settings.hashtag_mode` | `recent` | `top` (fewer, popular) / `recent` / `both`. |
| `settings.hashtag_medias_per_tag` | `30` | Posts scanned per hashtag. |
| `settings.max_candidates` | `400` | Hard cap on profiles enriched (0 = no cap). |
| `scoring.min_followers` | `1000` | Ignore accounts smaller than this. |
| `scoring.max_followers` | `500000` | Ignore accounts bigger than this. |
| `scoring.max_days_since_last_post` | `30` | Recency window to count as active. |
| `scoring.min_engagement_pct` | `0.0` | Optional engagement gate (0 = off). |
| `scoring.engagement_sample_posts` | `0` | Recent posts to sample (0 = off, fewer calls). |
| `commerce_keywords` | `shop, store, ...` | Substrings hinting an account sells. |
| `niches[].name` | — | Product category (auto-slugged to a hashtag). |
| `niches[].hashtags` | `[]` | Extra hashtags to scan. |
| `niches[].max_authors` | `200` | Max candidates this niche contributes. |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ChallengeRequired` on login | Use **sessionid** mode (Option A), or approve the login in the Instagram app (Settings → Security → Login activity). |
| `Sessionid login failed` | The cookie expired or Instagram rejected a web session. Copy a **fresh** `sessionid`, or use an older account with password login. |
| Login works, then requests fail / `PleaseWaitFewMinutes` / 429 | You're being throttled. Raise `per_request_delay_sec`, lower `max_candidates`, and wait before retrying. |
| Very few or zero leads | Widen `scoring.min_followers`/`max_followers` and `max_days_since_last_post`; add more specific tags; check `Why excluded` on the All Candidates sheet. |
| `pip install` errors | Use Python **3.10–3.12**; try upgrading pip (`pip install -U pip`). |
| Instagram changed its API | Update the library: `.venv/bin/pip install -U instagrapi`. |

---

## Sharing this repo safely (security & privacy)

This project is designed so you can hand it to someone else **without leaking
your account or their data**. Before you zip/copy/push it, read this.

**Files that must never be shared** (all are in `.gitignore`, but if you copy
the *folder* rather than `git clone`, gitignore doesn't protect you):

- **`.env`** — your Instagram username/password and/or `sessionid` cookie.
- **`session.json`** — a live, authenticated Instagram session token. Anyone with
  this file can use your account.
- **`output/*.xlsx`** — contains business contact details (emails/phones) = PII.
- **`config.yaml`** — your personal niches/settings (not secret, but pointless
  for someone else).

**Sharing checklist:**

```bash
# If you copied/zipped the folder, delete the sensitive bits first:
rm -f .env session.json
rm -rf output/ .venv/ __pycache__/
# Then share the rest — the recipient runs the Quick start steps themselves.
```

**What *is* safe to share:** all source code, `requirements.txt`,
`config.example.yaml`, `.env.example` (placeholders only), and `README.md`.

**Other safeguards:**

- **Only `.env.example` and `config.example.yaml` contain placeholders** — never
  put real credentials in a file with `example` in the name.
- **Use a throwaway Instagram account.** Not your main.
- **If you ever leak a `sessionid` or password, change that account's password**
  immediately — it invalidates all existing sessions.
- **Respect privacy.** The tool reads only publicly visible profile data and
  writes contact info to a local file — treat the output as personal data
  (GDPR/CCPA) and don't publish it. No data is sent anywhere except Instagram;
  there is no telemetry.
- **Public data only** — no private accounts, DMs, or follower scraping.

---

## Project structure

```
Social_Scraper/
├── run.py                  # CLI entry point
├── config.example.yaml     # copy to config.yaml and edit
├── .env.example            # copy to .env and add login (placeholders only)
├── requirements.txt
├── session.json            # created on first login (gitignored — secret)
├── .env                    # your secrets (gitignored)
├── output/                 # generated .xlsx files (gitignored)
└── igscraper/
    ├── config.py           # loads config.yaml + .env
    ├── client.py           # instagrapi wrapper: sessionid/password login, pacing
    ├── discovery.py        # niche -> hashtags -> candidate accounts
    ├── enrich.py           # full profiles + recent-post activity
    ├── scoring.py          # product/active/contact gates + 0–100 score
    └── export.py           # builds the Excel workbook
```

---

## Legal note

Automated access to Instagram's private API is against Instagram's Terms of
Service and can get the account you use rate-limited, challenged, or banned.
This tool is meant for small-scale, personal lead research on **public** data
with a spare account that you don't mind losing. Your account, your risk.
