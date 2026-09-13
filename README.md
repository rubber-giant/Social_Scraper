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
- [Discovery strategies](#discovery-strategies)
- [Config reference](#config-reference)
- [Troubleshooting](#troubleshooting)
- [Sharing this repo safely (security & privacy)](#sharing-this-repo-safely-security--privacy)
- [Project structure](#project-structure)

---

## How it works

1. **Discover** — for each niche, finds candidate accounts through several
   strategies (hashtag feeds, keyword account search, and seed-based lookalike
   expansion), merged and de-duplicated across niches. See
   [Discovery strategies](#discovery-strategies).
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

# preview the discovery plan + request estimate WITHOUT logging in or scraping
.venv/bin/python run.py discover --dry-run

# run only some strategies, or only one niche
.venv/bin/python run.py discover --strategies hashtag,chaining
.venv/bin/python run.py discover --only-niche candles
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
`Product signals`, `Matched niche`, `Found via`, `Discovery sources`,
`Relevance`, `Why excluded`.

---

## Tuning runtime & lead volume

Two things decide how long a run takes and how many leads you get: **how many
candidates** you collect, and **how long each candidate takes**.

**Rules of thumb** (~2 requests per candidate):

- **Time ≈ candidates × ~1 minute.**
- **Leads ≈ 15–20% of candidates.**

> **Pacing — why a run takes hours.** instagrapi sleeps `settings.request_timeout`
> (default `30`) before *every* non-login request as anti-ban pacing, and *then*
> adds the `delay_range` (`per_request_delay_sec` + jitter, default 3–5 s). So one
> request costs `request_timeout + delay` ≈ **34 s**. That — not your CPU — is
> what dominates a run. Lowering it speeds things up but raises the chance
> Instagram throttles or flags the account; see
> [Which knobs to turn](#which-knobs-to-turn).

**Measured example** (this project, default settings): `#jwellery` + `#tshirts`
niches → **150 candidates → 27 leads**, and the run took **~3 hours**. So:

| Candidates | Approx time | Approx leads |
|-----------:|------------:|-------------:|
| 20         | ~20 min     | 3–4          |
| 50         | ~50 min     | 8–10         |
| 150        | ~3 h        | ~27 (measured) |
| 400        | ~7–8 h      | 60–80        |

### Which knobs to turn

| Knob | Where | Effect on time | Effect on leads |
|---|---|---|---|
| `per_request_delay_sec` / `request_delay_jitter` | `settings` | ↓ = faster, more risk — but only the 3–5 s part of the ~34 s | none |
| `request_timeout` | `settings` | **dominant knob**: the 30 s pre-request sleep *and* the socket timeout. ↓ = far faster; too low → timeouts (60 s retry) | none |
| `hashtag_medias_per_tag` | `settings` | ↑ = more candidates = more time | ↑ |
| `hashtag_mode` (`top`/`recent`/`both`) | `settings` | `both` ≈ 2× discovery | ↑ |
| `niches[].max_authors` | per niche | caps that niche's candidates | caps it |
| `max_candidates` | `settings` | hard cap on total enriched | caps total |
| `discovery.enabled` | `discovery` | removing strategies = less discovery | ↓ |
| `discovery.max_requests_per_run` | `discovery` | hard wall on discovery requests | caps it |
| `discovery.per_strategy_max` | `discovery` | caps each strategy's candidates/niche | caps it |
| `niches[].seeds` / `keyword_queries` | per niche | ↑ sources = more candidates = more time | ↑ |
| `discovery.relevance.action: drop` | `discovery` | free (filtering) | ↓ noise |
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

A niche is a keyword plus the inputs that feed each strategy (hashtags, and
optionally `keyword_queries` / `seeds` — see
[Discovery strategies](#discovery-strategies)). The name is auto-slugged into a
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

## Discovery strategies

Accounts are found through up to three strategies, merged and de-duplicated,
then capped per niche by **provenance priority** (higher weight survives the cap
first). Configure under `discovery:` in `config.yaml`.

| Strategy | What it does | Needs | Request cost | Risk | Default |
|---|---|---|---|---|---|
| `hashtag` | Authors of posts under the niche's tags. | `niches[].hashtags` | tags × feeds | medium | on |
| `keyword` | Account search on brand-intent queries (`"jewelry store"`). Finds brands by name/bio even if they never use your tags. | `niches[].keyword_queries` | queries | medium | on (inert until set) |
| `chaining` | Instagram's own **"similar accounts"** for each seed brand — looks for *lookalikes* of brands you already know. | `niches[].seeds` (+ auto seed pool) | 2 × seeds | **low** | on (inert until set) |

`keyword` and `chaining` are inert until you give them input, so an existing
hashtag-only `config.yaml` behaves exactly as before.

### How to use them

Everything is per-niche. `hashtags` feeds `hashtag`, `keyword_queries` feeds
`keyword`, `seeds` feeds `chaining` — set any combination:

```yaml
niches:
  - name: jwellery
    max_authors: 80

    # hashtag: authors of posts under these tags (plus the niche name's slug).
    hashtags: [jewellerybrand, handmadejewellery]

    # keyword: Instagram account search on brand-intent phrases. Use language
    # a shopper/brand would use, not your own category word: "jewelry store"
    # finds businesses; "jewelry" finds everything. 2-4 per niche.
    keyword_queries: ["jewelry store", "handmade jewelry brand"]

    # chaining: brands to find *lookalikes* of. 2-4 handles you already know
    # that sit near your target size (see "Pick seeds near your target size").
    seeds: [mejuri, linjerco]

    # relevance: extra words that count as niche fit for the flag column.
    relevance_keywords: [jewelry, necklace, ring, gold, silver]
```

To run just one of them (handy while testing), use
`--strategies keyword` or `--strategies chaining` — see
[Running it](#running-it).

### Seeds & the auto-growing seed pool

`chaining` expands each **seed** to find similar brands, so it needs seeds:

- **Manual** — list 2–4 known brand handles per niche: `seeds: [brand_a, brand_b]`.
- **Automatic** — every run writes your strongest qualifying leads (score ≥
  `seed_pool.min_score`) to `output/seed_pool.json` and reuses them as seeds next
  run. Coverage compounds: run once, then each run finds lookalikes of the best
  accounts found so far. (`output/` is gitignored, so this never leaks.)

The two also combine within a run: strong `keyword` hits are reused as seeds for
`chaining` in the same run (`chaining.max_seeds_from_keyword`).

**Pick seeds near your target size.** A lookalike of a giant seed is a giant —
chaining from a luxury megabrand returns more megabrands, which then fail
`scoring.max_followers` and waste the run. Seeds work best when they're inside
(or just above) your target follower band, since Instagram's similarity graph
clusters by size and market. Prefer mid-size, on-niche brands; let the seed pool
grow from *qualifying* leads (which already pass your size gate) rather than
seeding by hand from famous names.

### Provenance & the relevance check

- **`Discovery sources`** (Excel column) shows every surface that found an
  account, e.g. `similar to @brand; search: 'jewelry store'; #jewellerybrand`.
- **Fit vs. recall:** `source_weights` decide rank order, and
  `source_share` stops the heaviest source from filling a niche's whole
  `max_authors` cap. By default `chaining` is capped to 50%, so half of each
  niche's slots go to `keyword`/`hashtag` instead of all to lookalikes. Any
  slots the others leave unused are backfilled, so nothing is wasted.
- **`Relevance`** samples the account's own recent posts (reusing a request the
  tool already makes — **no extra cost**) and lists the niche keywords they
  actually contain. This catches accounts surfaced by a broad tag that don't
  really fit the niche. By default it only **flags** (`action: flag`); set
  `action: drop` to exclude non-matching accounts from `Top Leads`.
- Optional `discovery.provenance_bonus` adds a small score bonus by source
  (0 = off, scoring unchanged).

### Cost control

- `discovery.max_requests_per_run` is a hard cap on Instagram requests per run
  (0 = unlimited). Strategies stop gracefully when it's hit, so a run can't blow
  up in time no matter how many tags/seeds/queries you configure.
- `discovery.per_strategy_max.<strategy>` caps how many candidates each strategy
  adds per niche.
- Budget check: `~ discover_requests + 2 × candidates` (see
  [Tuning runtime](#tuning-runtime--lead-volume) for the per-request cost).

> A `chaining` seed that's private or ineligible simply logs and is skipped, and
> an empty result falls back to a public GraphQL lookup (`chaining.fallback_gql`).

---

## Config reference

`config.yaml` mirrors `config.example.yaml`; every key is optional.

| Key | Default | Meaning |
|---|---|---|
| `settings.per_request_delay_sec` | `3.0` | Base seconds between requests. |
| `settings.request_delay_jitter` | `2.0` | Random extra seconds added per request. |
| `settings.request_timeout` | `30` | **Dominant pacing knob** (instagrapi sleeps it pre-request) *and* the socket timeout. Lower = much faster; too low raises timeouts. |
| `settings.hashtag_mode` | `recent` | `top` (fewer, popular) / `recent` / `both`. |
| `settings.hashtag_medias_per_tag` | `30` | Posts scanned per hashtag. |
| `settings.max_candidates` | `400` | Hard cap on profiles enriched (0 = no cap). |
| `scoring.min_followers` | `1000` | Ignore accounts smaller than this. |
| `scoring.max_followers` | `500000` | Ignore accounts bigger than this. |
| `scoring.max_days_since_last_post` | `30` | Recency window to count as active. |
| `scoring.min_engagement_pct` | `0.0` | Optional engagement gate (0 = off). |
| `scoring.engagement_sample_posts` | `0` | Recent posts to sample (0 = off, fewer calls). |
| `commerce_keywords` | `shop, store, ...` | Substrings hinting an account sells. |
| `discovery.enabled` | `[hashtag, keyword, chaining]` | Which strategies run. |
| `discovery.max_requests_per_run` | `400` | Hard cap on requests per run (0 = unlimited). |
| `discovery.per_strategy_max.<s>` | varies | Max candidates each strategy adds per niche. |
| `discovery.source_weights.<s>` | `chaining 2.0, keyword 1.5, hashtag 1.0` | Provenance priority for the niche cap. |
| `discovery.source_share.<s>` | `chaining 0.5` | Cap on a strategy's share of `max_authors` (fraction); leftover slots backfilled. |
| `discovery.provenance_bonus` | `0` | Optional score bonus by source (0 = off). |
| `discovery.hashtag.mode` / `medias_per_tag` | `null` | Overrides `settings.hashtag_*` when set. |
| `discovery.keyword.per_query` / `max_queries_per_niche` | `30` / `4` | Account-search breadth. |
| `discovery.chaining.per_seed` / `max_seeds_per_niche` | `12` / `8` | Lookalikes per seed / seeds per niche. |
| `discovery.chaining.max_seeds_from_keyword` | `3` | Keyword hits reused as same-run seeds. |
| `discovery.seed_pool.enabled` / `per_niche` / `min_score` | `true` / `10` / `70` | Auto-growing seed pool. |
| `discovery.seed_pool.state_path` | `output/seed_pool.json` | Where the pool is stored (gitignored). |
| `discovery.relevance.enabled` | `true` | Niche-fit check (reuses enrich's media call). |
| `discovery.relevance.action` | `flag` | `flag` (never drops) or `drop` (gates Top Leads). |
| `niches[].name` | — | Product category (auto-slugged to a hashtag). |
| `niches[].hashtags` | `[]` | Extra hashtags to scan. |
| `niches[].max_authors` | `200` | Max candidates this niche contributes. |
| `niches[].seeds` | `[]` | Known brands to find lookalikes of (chaining). |
| `niches[].keyword_queries` | `[]` | Brand-intent account-search queries. |
| `niches[].relevance_keywords` | `[]` | Extra words counted as niche fit. |

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
├── output/                 # generated .xlsx + seed_pool.json (gitignored)
└── igscraper/
    ├── config.py           # loads config.yaml + .env
    ├── client.py           # instagrapi wrapper: login, pacing, discovery calls
    ├── models.py           # Source / Candidate / DiscoveryResult
    ├── discovery.py        # niche -> candidate accounts (multi-strategy)
    ├── strategies.py       # hashtag / keyword / chaining strategies + budget
    ├── seedpool.py         # persists strong leads as next run's seeds
    ├── relevance.py        # niche-fit check on sampled post captions
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
