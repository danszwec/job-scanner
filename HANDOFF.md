# Handoff — Job Scanner

Daily scanner that finds new Israeli job postings matching a profile and emails a digest.
Runs free on GitHub Actions. Code: **https://github.com/danszwec/job-scanner**.

Design in [DESIGN.md](DESIGN.md), usage in [README.md](README.md).

## Status: live

Working end to end as of **2026-08-22**. Run #26 was the first green run after 25
consecutive failures.

- **97 companies** across 7 ATS providers: 44 Greenhouse, 24 Comeet, 15 Ashby,
  5 SmartRecruiters, 5 Workday, 3 Lever, 1 Workable.
- **~5,500 openings scanned per run, ~98 matched**, 100 seconds, 97/97 endpoints OK.
- **144 tests.** `uv run pytest tests/ -q`.
- Sends at **18:15 Israel time**, every day.
- Recipients: Shani and Dan (the `RECIPIENT` secret takes a comma-separated list).

## How it works

```
companies.yaml → fetch every ATS → filter → dedup against seen.sqlite → email → commit ledger
```

The runner is wiped after each run, so the workflow **commits `seen.sqlite` and `jobs.csv`
back to the repo** — that commit is the memory. Look for `chore: daily scan ledger <date>`
from `job-scanner-bot`.

**Dedup** is by `job_uid` (`{provider}:{board_id}`), the primary key of the `jobs` table.
`emailed` is 0 until a send succeeds, then 1. A job already in the table is never a
candidate again. `mark_emailed` runs *only* on a successful send, so a failed send leaves
the rows at 0 and the next run retries them rather than dropping them.

**The filter** matches roles, not keywords. A title needs a DOMAIN word (product, project,
operations, brand, marketing, creative…) next to a HEAD noun (manager, coordinator,
designer, specialist…), in either order. `engineer`, `developer`, `architect` and
`scientist` are deliberately *not* head nouns, which is what keeps technical titles out
without a blocklist. "Engineering Manager" has a head but no domain and drops; "Software
Project Manager" has both and stays. Plus a seniority exclude, an Israel-location rule and
a 45-day freshness cap. See `scanner/filters.py`.

The KEEP / DROP lists in `tests/test_filters.py` are the profile spec. **Change those
first** when the target changes.

## Secrets

Settings → Secrets and variables → Actions:

| secret | value |
|---|---|
| `GMAIL_USER` | `shani.jobscanner@gmail.com` |
| `GMAIL_APP_PASSWORD` | 16-char Gmail app password, **no spaces** |
| `RECIPIENT` | one or more addresses, comma-separated |

Settings → Actions → General → Workflow permissions must be **Read and write**, or the
ledger commit fails.

The app password needs 2-Step Verification on the sending account. That was the original
blocker: the account existed but had no 2FA, so no app password could exist, and every run
failed at login.

## Running it

```bash
uv sync
uv run pytest tests/ -q
uv run python -m scanner.run --dry-run   # prints the digest; never touches the ledger
uv run python -m scanner.run --seed      # marks everything live as sent, no email
uv run python -m scanner.run             # real run (needs the Gmail env vars)
```

`--dry-run` and `--seed` are also available as checkboxes on **Actions → Daily job scan →
Run workflow**, so neither needs a local checkout.

## Things that will confuse you later

- **Two cron entries, on purpose.** GitHub cron is UTC with no DST awareness, so no single
  entry holds a fixed local time. Both 15:15 and 16:15 UTC fire daily and the "Right hour?"
  step drops whichever is not 18:xx in Israel. A skipped run reports success and does
  nothing — a skip is not a failure.
- **Gmail clips bodies over ~102 KB.** The digest cards the first 50 roles and lists the
  rest compactly, which keeps any digest under ~97 KB. A normal night is 6 KB.
- **No apostrophes in the font stacks** in `email_digest.py`. Style attributes are
  single-quoted, so a quoted font name closes the attribute early and silently drops every
  declaration after it. `font-family` is written last in every style for the same reason,
  and the tests fail if that ordering breaks.
- **Workday needs the location facet, not `searchText`.** `searchText` is free text over
  the whole posting: it found none of Salesforce's Israeli roles and matched Illinois on
  PayPal. Also, Workday reports `total` on the first page only — trusting it on later pages
  capped every tenant at 40 postings.
- **Comeet tokens are per-company** and scraped from the public careers page. They are in
  `companies.yaml`. Not secret (they come off public pages) but they do rotate.

## Known gaps

- **Duplicate postings.** Dedup keys on the provider's board id, so a role deleted and
  re-posted gets a new id and is sent twice. No occurrences observed, but it is real. A
  secondary `(company, title, location)` key would close it.
- **`posted_at` is not stored.** A job recorded but never emailed stays a candidate
  forever and could be sent after going stale. Needs a column and a migration.
- **No alarm on silent zeros.** OpenWeb's board returns 0 and PayPal's Workday has no
  Israeli roles; both count as "ok". A company could die unnoticed. Wants a warning after
  N consecutive empty days.
- **The repo is public** and this file names the sending and receiving addresses.
- Workday's "Posted 30+ Days Ago" is treated as stale and dropped, which is stricter than
  the 45-day rule. Workday gives no real dates, so there is no better signal.

## Growing the company list

Edit `companies.yaml`; the header documents the fields per provider. Verify any new entry
against live job data before trusting it — slug guessing produced eight convincing false
positives during the last pass (`greenhouse/fox` is a veterinary clinic, `ashby/tailor` is
a Japanese firm, `lever/bloom` is a Canadian retailer).

**Do not re-run the discovery sweep on Shani's remaining companies expecting a better
answer.** Three passes were done — static HTML, slug guessing, then a headless browser
capturing every request. The reasons the rest are unreachable are written at the bottom of
`companies.yaml`. In short: most proxy their ATS server-side so the credentials never reach
the client, and the creative studios and retail brands have no machine-readable board at
all. Adding those means a per-company HTML scraper that breaks whenever they restyle.
