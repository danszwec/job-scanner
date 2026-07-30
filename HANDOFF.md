# Handoff — Job Scanner

Everything needed to run and finish this project. All code is in git at
**https://github.com/danszwec/job-scanner** (personal account `danszwec`).

## What this is

A daily scanner that finds new Israeli job postings matching a profile and emails a
digest to shani.shahar1997@gmail.com. Runs free on GitHub Actions at 21:30 IST. Never
emails the same job twice (SQLite dedup ledger committed back to the repo each run).
Full design in [DESIGN.md](DESIGN.md); usage in [README.md](README.md).

- 69 companies in `companies.yaml` across 6 ATS providers (Greenhouse, Lever, Comeet,
  SmartRecruiters, Workday, Ashby).
- Filter: title contains product/project/manager/coordination/creative/operations/brand
  (EN+HE), excludes senior/lead, Israel-only, posted within 45 days.

## Current status (as of handoff)

- ✅ Code written, tested, pushed to GitHub. Repo is currently **public** (flip to private
  when done — nothing secret is in it).
- ✅ GitHub Actions workflow installed (`.github/workflows/daily.yml`).
- ⚠️ **Email sending NOT yet working.** The workflow runs but fails at Gmail login with
  `SMTPAuthenticationError (535)`. **Root cause: the `GMAIL_APP_PASSWORD` secret was
  entered WITH spaces.** Gmail needs the 16 characters with NO spaces.
- ℹ️ Ledger was reset locally to send a full first digest for testing, but that reset was
  **not pushed** (needs a token — see below). The repo still has the seeded ledger.

## TO FINISH — remaining steps

### 1. Fix the email (the one real blocker)
In the GitHub repo → **Settings → Secrets and variables → Actions**:
- `GMAIL_USER` = `shani.jobscanner@gmail.com`
- `GMAIL_APP_PASSWORD` = the 16-char Gmail app password **with spaces removed**
  (e.g. `abcd efgh ijkl mnop` → `abcdefghijklmnop`).
  Generate/refresh at https://myaccount.google.com/apppasswords (signed in as
  shani.jobscanner). Requires 2-Step Verification ON (already done).
- `RECIPIENT` = `shani.shahar1997@gmail.com` (or set to shani.jobscanner@gmail.com first
  to test to yourself, then switch).

### 2. Allow the daily ledger commit
Settings → **Actions → General → Workflow permissions → "Read and write permissions"** → Save.
(Without this, the daily commit of `seen.sqlite` fails.)

### 3. Test
Actions tab → **Daily job scan → Run workflow**. With the ledger seeded it will email
"No new jobs today" (correct — proves delivery works). To test a REAL digest, run
`python -m scanner.run --seed` locally is the opposite; instead delete `seen.sqlite`,
commit, push, then run — it will email the full current list once.

### 4. Go live
Once the test email arrives, it's autonomous — runs 21:30 IST daily. Flip repo to
**private** if desired.

## Handover to a new Claude / new machine

Nothing is hidden on the old machine. To continue elsewhere:

```bash
git clone https://github.com/danszwec/job-scanner.git
cd job-scanner
uv sync                              # rebuild the venv from uv.lock
uv run python -m scanner.run --dry-run   # test locally (no email)
```

- **Secrets are NOT in git** (correct). They live only in GitHub repo secrets. The new
  person just needs the 3 secret values (Gmail user / app password / recipient).
- **The ledger (`seen.sqlite`, `jobs.csv`) IS in git** — that's the dedup memory; keep it.
- To push changes later: any GitHub account with write access to the repo, or a
  fine-grained PAT with **Contents: Read/write** (+ **Workflows: Read/write** if editing
  `.github/workflows/`).
- To grow the company list: edit `companies.yaml` (format documented in README), or ask
  Claude to "add more companies" — it runs a discovery pass.

## TODO — email template & CTR (not done yet)

The current email (`scanner/email_digest.py` → `render_html`) is functional but plain:
company headers + text links. Needs a real design pass:

- **Colors / branded template.** Pick a theme (options discussed: warm coral/peach,
  professional blue/teal, modern purple/violet) and build a proper HTML email — header
  bar with accent color + title, each company as a card, each job as a row with a
  location pill.
- **CTR (click optimization).** Replace bare text links with a clear tappable
  **"View job →" button** per job (bigger tap target → more clicks). Note: real click
  *tracking/measurement* would need a server or an email service (Resend/SendGrid) — we
  deliberately skipped that. "CTR" here means designing for clicks, not measuring them.
  If measurement is wanted later, that's a separate infra decision.
- **Language / direction.** Decide English (LTR) vs Hebrew (RTL) vs a Hebrew-greeting /
  English-labels hybrid — the recipient is Israeli, so RTL Hebrew may feel more natural.
  Job titles stay as posted (mixed HE/EN).

All of this is isolated to `render_html` in `scanner/email_digest.py` — no other file
changes needed.

## Known follow-ups / nice-to-haves

- `git pull` before running locally so the ledger stays current.
- Node.js-20 deprecation warning in Actions is harmless (actions still run on Node 24).
- One-off transient network errors on a single company just skip that company for the
  day; the run continues (by design).
- To reach 100+ companies, add more ATS providers (e.g. Rippling) or more Comeet
  companies (each needs its uid + token scraped from the public page).

## The manual first list

`jobs_for_shani.csv` (in the repo root) — 113 matched jobs from the first scan, ready to
open in Excel and send to Shani manually while the email pipeline is being finished.
