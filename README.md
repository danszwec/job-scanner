# Job Scanner

Daily scanner that finds new job postings matching a profile, emails a digest, and never
shows the same job twice. Runs free on GitHub Actions. See [DESIGN.md](DESIGN.md) for the
full design.

## What it does

Every day at **18:15 Israel time** it:
1. fetches openings from the 97 companies in `companies.yaml` (via their ATS JSON APIs),
2. keeps only titles that name a target **role** — a domain word (product / project /
   operations / brand / marketing / creative / coordination) next to a head noun (manager
   / coordinator / designer / specialist), excluding senior and technical ones — located
   in **Israel** and posted in the last 45 days,
3. drops anything already emailed before,
4. emails the new ones, and commits the updated ledger back to the repo.

Roughly 5,500 openings scanned per run, around 98 matching.

Supported ATS providers: Greenhouse, Lever, Comeet, SmartRecruiters, Workday, Ashby,
Workable.

## Setup

1. **Push this repo to GitHub.**
2. **Create a Gmail app password** (Google Account → Security → 2-Step Verification →
   App passwords). 16 characters.
3. **Add three repo secrets** (Settings → Secrets and variables → Actions):
   - `GMAIL_USER` — the sending Gmail address
   - `GMAIL_APP_PASSWORD` — the app password from step 2
   - `RECIPIENT` — where the digest goes; comma-separate for several addresses
4. Set Settings → Actions → General → Workflow permissions to **Read and write**, or
   the ledger commit fails.
5. Done. The workflow runs daily; you can also trigger it manually from the **Actions**
   tab (**Daily job scan → Run workflow**), where `dry_run` and `seed` are checkboxes.

The app password requires 2-Step Verification on the sending account — without it the
App passwords page does not exist and every run fails at login.

## Local use

```bash
uv sync
uv run pytest tests/ -q                    # 144 tests
uv run python -m scanner.run --dry-run     # print the digest; never touches the ledger
uv run python -m scanner.run --seed        # mark everything live as sent, no email
```

For a real local send, export `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `RECIPIENT` first.

## Adding companies

Edit `companies.yaml`. Fields per provider:

| source          | fields                                   |
|-----------------|------------------------------------------|
| greenhouse      | `name`, `slug`                           |
| lever           | `name`, `slug`                           |
| comeet          | `name`, `uid`, `token`                   |
| ashby           | `name`, `slug`                           |
| workable        | `name`, `slug`                           |
| smartrecruiters | `name`, `slug` (often ends in a digit)   |
| workday         | `name`, `tenant`, `site`, `wd_host`      |

Optional `is_israeli: false` for a non-Israeli company (changes how ambiguous locations
are treated).

Verify any new entry against live job data before trusting it. Guessing slugs produces
convincing false positives — `greenhouse/fox` is a veterinary clinic, `ashby/tailor` is a
Japanese firm.

## The ledger

- `seen.sqlite` — dedup memory (which jobs were already emailed) + run-health log.
- `jobs.csv` — human-readable mirror of every job ever matched.

Both are committed by the daily workflow so the stateless runner remembers across days.
