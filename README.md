# Job Scanner

Daily scanner that finds new job postings matching a profile, emails a digest, and never
shows the same job twice. Runs free on GitHub Actions. See [DESIGN.md](DESIGN.md) for the
full design.

## What it does

Every day at ~21:30 Israel time it:
1. fetches openings from the companies in `companies.yaml` (via their ATS JSON APIs),
2. keeps only titles matching **product / project / manager / coordination / creative /
   operations / brand** (excluding **senior / lead**), located in **Israel**,
3. drops anything already emailed before,
4. emails the new ones, and commits the updated ledger back to the repo.

Supported ATS providers: Greenhouse, Lever, Comeet, SmartRecruiters, Workday.

## Setup

1. **Push this repo to GitHub.**
2. **Create a Gmail app password** (Google Account → Security → 2-Step Verification →
   App passwords). 16 characters.
3. **Add three repo secrets** (Settings → Secrets and variables → Actions):
   - `GMAIL_USER` — the sending Gmail address
   - `GMAIL_APP_PASSWORD` — the app password from step 2
   - `RECIPIENT` — where the digest goes (e.g. shanishahar1997@gmail.com)
4. Done. The workflow runs daily; you can also trigger it manually from the **Actions**
   tab (**Daily job scan → Run workflow**).

## Local use

```bash
uv sync
uv run python -m scanner.run --dry-run     # print the digest, no email, no send-marking
```

For a real local send, export `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `RECIPIENT` first.

## Adding companies

Edit `companies.yaml`. Fields per provider:

| source          | fields                                   |
|-----------------|------------------------------------------|
| greenhouse      | `name`, `slug`                           |
| lever           | `name`, `slug`                           |
| comeet          | `name`, `uid`, `token`                   |
| smartrecruiters | `name`, `slug` (often ends in a digit)   |
| workday         | `name`, `tenant`, `site`, `wd_host`      |

Optional `is_israeli: false` for a non-Israeli company (changes how ambiguous locations
are treated). To discover more companies, ask Claude to run a discovery pass.

## The ledger

- `seen.sqlite` — dedup memory (which jobs were already emailed) + run-health log.
- `jobs.csv` — human-readable mirror of every job ever matched.

Both are committed by the daily workflow so the stateless runner remembers across days.
