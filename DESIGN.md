# Job Scanner — Design

A daily automated scanner that finds new job postings matching a profile, emails a
digest, and never shows the same job twice.

## Who / what

- **User:** built for my girlfriend. She receives one email per day.
- **Profile filter (the matching rule):**
  - Title **must include** at least one of: `project`, `product`, `manager`,
    `coordination` (coordinator), `creative`, `operations`, `brand`
    — plus Hebrew equivalents (see keyword map below).
  - Title **must NOT include**: `senior`, `lead` (+ Hebrew: `בכיר/ה`, `מוביל/ה`, `ראש צוות`).
  - **Location:** Israel only (include when a company is Israel-based and the listing
    does not clearly state another country — see location rule).

## Architecture (all free, no server)

```
                         ┌─────────────────────────────────────────┐
   companies.yaml ──────▶│  GitHub Action (cron, daily ~07:00 IST)  │
   (verified ATS slugs)  │                                          │
                         │  1. fetch each ATS JSON endpoint         │
                         │  2. filter by title keywords + location  │
                         │  3. diff against seen.sqlite (job IDs)   │
                         │  4. render HTML digest of NEW jobs only  │
                         │  5. send via Gmail SMTP (app password)   │
                         │  6. commit updated seen.sqlite + jobs.csv│
                         └─────────────────────────────────────────┘
```

- **Daily source:** per-company ATS JSON endpoints only (deterministic, free, stable IDs).

  | ATS            | Endpoint pattern                                                        | Method |
  |----------------|-------------------------------------------------------------------------|--------|
  | Greenhouse     | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`            | GET    |
  | Lever          | `api.lever.co/v0/postings/{slug}?mode=json`                             | GET    |
  | Comeet         | `comeet.com/careers-api/2.0/company/{slug}/positions`                    | GET    |
  | Workable       | `apply.workable.com/api/v3/accounts/{slug}/jobs`                         | POST   |
  | SmartRecruiters| `api.smartrecruiters.com/v1/companies/{slug}/postings`                   | GET    |
  | Workday        | `{tenant}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`               | POST   |

- **Email:** Gmail + app password over SMTP (`smtp.gmail.com:465`).
- **Hosting:** GitHub Actions scheduled workflow. No always-on machine needed.
- **Storage (the table):** committed to the repo so it persists between runs.
  - `seen.sqlite` — dedup ledger, keyed on `job_uid`.
  - `jobs.csv` — human-readable full table of every job ever matched.

## Two files, opposite jobs

- **`companies.yaml` = INPUT (what to scan).** The watchlist of companies + which ATS
  each uses. You maintain it; I seed & grow it. Rarely changes.
- **`jobs.csv` / `seen.sqlite` = OUTPUT/MEMORY (what we found).** The record of every
  matching job ever seen — the scanner writes it. Its whole purpose is "never email the
  same job twice."

## The table (`jobs` — persisted, deduped)

| column        | meaning                                                             |
|---------------|---------------------------------------------------------------------|
| `job_uid`     | dedup key = `{source}:{board_job_id}` (primary key)                 |
| `title`       | job title as posted                                                 |
| `company`     | company name                                                        |
| `location`    | raw location string from the listing                                |
| `url`         | canonical apply/listing URL                                         |
| `source`      | `greenhouse`/`lever`/`comeet`/`workable`/`smartrecruiters`/`workday`|
| `first_seen`  | date first matched (the day it goes in the email)                   |
| `last_seen`   | last date the listing still appeared (for staleness)                |
| `emailed`     | 0/1 — has it been sent yet                                          |

**Dedup rule:** a job is "the same" iff `job_uid` matches. Board job IDs are stable, so a
re-crawl of an unchanged listing is recognized and never re-emailed. Fallback if a board
lacks an ID: `sha1(company|title|location)`.

**Never-email-twice:** the daily email contains only rows where `emailed = 0`. After a
successful send, those rows flip to `emailed = 1` and the DB is committed.

## Company list (`companies.yaml`)

- Seeded **now** by me via a web-search discovery pass; **each endpoint verified** (real
  HTTP → valid JSON) before it goes in the file.
- Scope: Israeli companies broadly — **tech AND non-tech** (consumer, retail, agency, media).
- Size: as many as I can verify in one pass.
- Format:
  ```yaml
  - name: Monday.com
    source: greenhouse        # greenhouse|lever|comeet|workable|smartrecruiters|workday
    slug: monday              # the {slug}/{tenant} in the endpoint URL
    # workday only: also needs `tenant` + `site`
  ```

## Discovery model — HYBRID (site: feeds the watchlist)

The daily engine never depends on live web search. Instead:

- **Discovery (periodic, run by me):** use Google `site:` queries to find companies, then
  extract the slug/tenant from each result URL, verify the endpoint, and append to
  `companies.yaml`. Example seed queries:
  - `site:myworkdayjobs.com "Tel Aviv"` / `"Israel"`
  - `site:jobs.lever.co "Israel"`
  - `site:apply.workable.com "תל אביב"`
  - `site:boards.greenhouse.io "Tel Aviv"`
  - `site:jobs.smartrecruiters.com "Israel"`
- **Daily scanning:** only the verified ATS JSON endpoints in `companies.yaml`.

This gives the broad reach of content-search + the reliability/dedup of structured JSON,
at $0/mo (no paid SERP API). To grow coverage: "add more companies" → I run another
discovery sweep.

## Keyword map (English + Hebrew)

Case-insensitive, **title only**, word-aware.

| concept       | English            | Hebrew (examples)                     |
|---------------|--------------------|---------------------------------------|
| product       | product            | מוצר, מנהל/ת מוצר                      |
| project       | project            | פרויקט, פרויקטים                       |
| manager       | manager            | מנהל, מנהלת, ניהול                     |
| coordination  | coordinat*         | רכז, רכזת, תיאום                       |
| creative      | creative           | קריאייטיב, יצירתי                      |
| operations    | operations, ops    | תפעול, מנהל/ת תפעול                    |
| brand         | brand              | מותג, מיתוג                           |
| **EXCLUDE**   | senior, lead       | בכיר, בכירה, מוביל, מובילה, ראש צוות   |

## Location rule

Include a job when:
- listing location mentions Israel / an Israeli city (Tel Aviv, תל אביב, Haifa, Herzliya,
  Jerusalem, Ramat Gan, Be'er Sheva, etc.), **OR**
- the company is Israel-based and the listing location is empty/remote/ambiguous and does
  **not** clearly name another country.

Exclude when the listing clearly names a non-Israel location.

## Email

- One email per day at **21:30 Israel time**. Window = jobs seen in the **last 24h**.
- Recipient: **shanishahar1997@gmail.com**.
- Subject: `N new jobs — {date}` (or `No new jobs today — {date}`).
- Body: grouped by company, each row = title (linked to `url`) + location. Clean, plain — no buttons/tracking.
- **Empty days:** still send a short "nothing new today" note so she knows it ran.
- **Cron caveat:** GitHub Actions cron is **UTC**. Use `30 18 * * *` UTC ≈ 21:30 IST in
  summer (UTC+3); accepts ~1h drift to 20:30 in winter (UTC+2). GitHub cron may also lag
  5–15 min under load — harmless here.

## Feedback loop (v1: minimal)

- **Loop A — run health (to me only).** Every run logs to a `runs` table: companies
  scanned, endpoints that failed, total openings, matched, new-emailed. Optional weekly
  self-summary email to **me** so broken slugs / ATS changes surface early.
- **Reaction tracking (👍/👎): deferred.** Adds a server or clunky mailto replies —
  not worth it for v1. Revisit once she's actually using the daily email.

## Secrets (GitHub repo secrets, never committed)

- `GMAIL_USER` — sender Gmail address
- `GMAIL_APP_PASSWORD` — 16-char app password
- `RECIPIENT` — her email address

## Repo layout

```
job-scanner/
├── DESIGN.md
├── companies.yaml
├── scanner/
│   ├── __init__.py
│   ├── sources.py         # 6 ATS fetchers
│   ├── filters.py         # title keyword + location matching
│   ├── store.py           # sqlite dedup ledger + csv export
│   ├── email_digest.py    # HTML render + Gmail SMTP send
│   └── run.py             # orchestrates the daily run
├── seen.sqlite
├── jobs.csv
├── pyproject.toml         # uv-managed
└── .github/workflows/
    └── daily.yml
```

## Build order

1. Scaffold repo (uv) + `sources.py`; verify all 6 endpoint shapes against live companies.
2. Web-search discovery pass → build & verify `companies.yaml`.
3. `filters.py` (keyword map + location) with unit tests on real titles.
4. `store.py` (sqlite + csv) with dedup tests.
5. `email_digest.py` — send a test email to yourself.
6. `run.py` wiring; dry-run locally.
7. `daily.yml` workflow + document the 3 secrets. First scheduled run.

## Open items to confirm before/at build

- Recipient email + sender Gmail (for secrets).
- Send time confirmed at 07:00 IST?
- Any must-have companies she already wants watched?
