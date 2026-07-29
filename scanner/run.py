"""Daily orchestrator: load companies -> fetch all -> filter -> dedup -> email -> persist.

Run locally:
    uv run python -m scanner.run --dry-run          # no email, no db writes reported as sent
    uv run python -m scanner.run                    # real run (needs Gmail env vars)

The GitHub Action calls the real run and then commits seen.sqlite + jobs.csv back.
"""

import argparse
import datetime
import os

import yaml

from scanner import email_digest, filters, sources, store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES_PATH = os.path.join(REPO_ROOT, "companies.yaml")
DB_PATH = os.path.join(REPO_ROOT, "seen.sqlite")
CSV_PATH = os.path.join(REPO_ROOT, "jobs.csv")

# Israel is UTC+2 (winter) / UTC+3 (summer). GitHub runners are UTC. We approximate IST
# as UTC+3 for the human-facing date label; being an hour off in winter is harmless.
IST_OFFSET = datetime.timedelta(hours=3)


def israel_today():
    now_ist = datetime.datetime.now(datetime.UTC) + IST_OFFSET
    return now_ist.date().isoformat()


def load_companies():
    with open(COMPANIES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def scan(companies):
    """Fetch every company, collect (all_jobs, per-company failures, counts)."""
    all_jobs = []
    failures = []
    ok = 0
    for company in companies:
        jobs, err = sources.fetch_company(company)
        if err:
            failures.append(f"{company.get('name', '?')}: {err}")
            continue
        ok += 1
        is_israeli = company.get("is_israeli", True)
        for j in jobs:
            j["_company_is_israeli"] = is_israeli
        all_jobs.extend(jobs)
    return all_jobs, failures, ok


def apply_filters(all_jobs):
    return [
        j
        for j in all_jobs
        if filters.passes(j, company_is_israeli=j.get("_company_is_israeli", True))
    ]


def main(dry_run=False, seed=False):
    today = israel_today()
    companies = load_companies()
    conn = store.connect(DB_PATH)

    all_jobs, failures, endpoints_ok = scan(companies)
    matched = apply_filters(all_jobs)

    # Staleness: mark everything currently live as seen today.
    store.touch_last_seen(conn, matched, today)

    # Dedup: only jobs we've never recorded become "new".
    new_jobs = store.filter_new(conn, matched)
    store.record_new(conn, new_jobs, today)

    # Seed mode: record today's backlog as already-emailed WITHOUT sending, so the first
    # real run only surfaces jobs posted after seeding. No email goes out.
    if seed:
        store.mark_emailed(conn, [j["job_uid"] for j in store.unemailed(conn)])
        store.export_csv(conn, CSV_PATH)
        print(f"[{today}] SEED: recorded {len(new_jobs)} jobs as seen; no email sent.")
        conn.close()
        return

    # The digest = unemailed rows (new_jobs, plus any that failed to send previously).
    to_email = store.unemailed(conn)
    subject = email_digest.subject_for(to_email, today)
    html = email_digest.render_html(to_email, today)

    email_digest.send_email(html, subject, dry_run=dry_run)

    if not dry_run:
        store.mark_emailed(conn, [j["job_uid"] for j in to_email])

    store.log_run(
        conn,
        {
            "run_date": today,
            "companies_total": len(companies),
            "endpoints_ok": endpoints_ok,
            "endpoints_fail": len(failures),
            "openings_total": len(all_jobs),
            "matched": len(matched),
            "new_emailed": len(to_email),
            "failures": "; ".join(failures),
        },
    )
    store.export_csv(conn, CSV_PATH)

    print(
        f"[{today}] companies={len(companies)} ok={endpoints_ok} fail={len(failures)} "
        f"openings={len(all_jobs)} matched={len(matched)} new={len(new_jobs)} "
        f"emailed={len(to_email)}{' (dry-run)' if dry_run else ''}"
    )
    if failures:
        print("  failures:", "; ".join(failures))
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="no email, print instead"
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="record current jobs as seen without emailing (run once before go-live)",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, seed=args.seed)
