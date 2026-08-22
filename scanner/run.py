"""Daily orchestrator: load companies -> fetch all -> filter -> dedup -> email -> persist.

Run locally:
    uv run python -m scanner.run --dry-run   # print the digest; never touches the ledger
    uv run python -m scanner.run --seed      # record today as already sent, no email
    uv run python -m scanner.run             # real run (needs Gmail env vars)

The GitHub Action calls the real run and then commits seen.sqlite + jobs.csv back.

A failed send does not abort the run. We persist the ledger and the run-health row first,
leave the jobs marked unemailed so tomorrow retries them, and only then exit non-zero. The
workflow commits the ledger with `if: always()`, so a broken mailbox never costs us the
scan results — which is exactly what happened for the 25 runs before this was fixed.
"""

import argparse
import datetime
import os
import sys

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


def write_step_summary(stats, send_error):
    """Put the run's numbers on the Actions run page, so a failure is readable without
    opening the log. No-op outside GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    status = "❌ email failed" if send_error else "✅ sent"
    rows = "\n".join(
        f"| {k.replace('_', ' ')} | {v} |"
        for k, v in stats.items()
        if k not in ("failures", "run_date")
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(
            f"## Daily scan {stats['run_date']} — {status}\n\n"
            f"| metric | value |\n|---|---|\n{rows}\n\n"
        )
        if stats["failures"]:
            f.write(f"**Failures**\n\n```\n{stats['failures']}\n```\n")


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

    # A dry run must not touch the ledger. Writing would record today's jobs as already
    # seen, so the next REAL run would find nothing new and email an empty digest.
    if dry_run:
        would_email = store.preview_new(conn, matched)
        email_digest.send_email(
            email_digest.render_html(would_email, today),
            email_digest.subject_for(would_email, today),
            dry_run=True,
        )
        print(
            f"[{today}] companies={len(companies)} ok={endpoints_ok} "
            f"fail={len(failures)} openings={len(all_jobs)} matched={len(matched)} "
            f"would_email={len(would_email)} (dry-run, ledger untouched)"
        )
        if failures:
            print("  failures:", "; ".join(failures))
        conn.close()
        return

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
    send_error = None
    try:
        email_digest.send_email(
            email_digest.render_html(to_email, today),
            email_digest.subject_for(to_email, today),
            text_body=email_digest.render_text(to_email, today),
        )
    except Exception as exc:  # noqa: BLE001 - any send failure must still persist below
        send_error = f"{type(exc).__name__}: {exc}"

    # Only mark them sent if they actually went out; otherwise tomorrow retries.
    if send_error is None:
        store.mark_emailed(conn, [j["job_uid"] for j in to_email])

    all_failures = failures + ([f"email: {send_error}"] if send_error else [])
    stats = {
        "run_date": today,
        "companies_total": len(companies),
        "endpoints_ok": endpoints_ok,
        "endpoints_fail": len(failures),
        "openings_total": len(all_jobs),
        "matched": len(matched),
        "new_emailed": 0 if send_error else len(to_email),
        "failures": "; ".join(all_failures),
    }
    store.log_run(conn, stats)
    store.export_csv(conn, CSV_PATH)
    conn.close()

    line = (
        f"[{today}] companies={len(companies)} ok={endpoints_ok} fail={len(failures)} "
        f"openings={len(all_jobs)} matched={len(matched)} new={len(new_jobs)} "
        f"emailed={stats['new_emailed']}"
    )
    print(line)
    if all_failures:
        print("  failures:", "; ".join(all_failures))
    write_step_summary(stats, send_error)

    if send_error:
        print(f"EMAIL FAILED: {send_error}", file=sys.stderr)
        sys.exit(1)


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
