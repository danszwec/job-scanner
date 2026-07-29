"""Persistence: the dedup ledger (sqlite) + human-readable csv export + run-health log.

The sqlite db is the source of truth for "have we seen this job before". It lives in the
repo and is committed after each run, so the ephemeral GitHub Actions runner carries
yesterday's memory forward. jobs.csv is a flat mirror for humans to browse.
"""

import csv
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_uid     TEXT PRIMARY KEY,
    title       TEXT,
    company     TEXT,
    location    TEXT,
    url         TEXT,
    source      TEXT,
    first_seen  TEXT,
    last_seen   TEXT,
    emailed     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    run_date        TEXT,
    companies_total INTEGER,
    endpoints_ok    INTEGER,
    endpoints_fail  INTEGER,
    openings_total  INTEGER,
    matched         INTEGER,
    new_emailed     INTEGER,
    failures        TEXT
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def filter_new(conn, jobs):
    """Return the subset of `jobs` whose job_uid is not already in the db.

    Also bumps last_seen for jobs we've seen before (staleness tracking).
    """
    new = []
    seen_uids = {r["job_uid"] for r in conn.execute("SELECT job_uid FROM jobs")}
    for job in jobs:
        if job["job_uid"] in seen_uids:
            continue
        new.append(job)
    return new


def record_new(conn, jobs, today):
    """Insert new jobs with emailed=0. Idempotent via INSERT OR IGNORE on the PK."""
    conn.executemany(
        """
        INSERT OR IGNORE INTO jobs
            (job_uid, title, company, location, url, source, first_seen, last_seen, emailed)
        VALUES (:job_uid, :title, :company, :location, :url, :source, :first_seen, :last_seen, 0)
        """,
        [{**j, "first_seen": today, "last_seen": today} for j in jobs],
    )
    conn.commit()


def touch_last_seen(conn, jobs, today):
    """Update last_seen for jobs currently live (any uid we passed in)."""
    conn.executemany(
        "UPDATE jobs SET last_seen = ? WHERE job_uid = ?",
        [(today, j["job_uid"]) for j in jobs],
    )
    conn.commit()


def unemailed(conn):
    """Rows that matched but haven't been emailed yet (the daily digest contents)."""
    return [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE emailed = 0")]


def mark_emailed(conn, job_uids):
    conn.executemany(
        "UPDATE jobs SET emailed = 1 WHERE job_uid = ?", [(u,) for u in job_uids]
    )
    conn.commit()


def log_run(conn, stats):
    """stats: dict with the run-health fields (Loop A)."""
    conn.execute(
        """
        INSERT INTO runs
            (run_date, companies_total, endpoints_ok, endpoints_fail,
             openings_total, matched, new_emailed, failures)
        VALUES (:run_date, :companies_total, :endpoints_ok, :endpoints_fail,
                :openings_total, :matched, :new_emailed, :failures)
        """,
        stats,
    )
    conn.commit()


def export_csv(conn, csv_path):
    """Mirror the jobs table to a flat csv, newest first."""
    rows = conn.execute("""
        SELECT job_uid, title, company, location, url, source, first_seen, last_seen, emailed
        FROM jobs ORDER BY first_seen DESC, company
        """).fetchall()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "job_uid",
                "title",
                "company",
                "location",
                "url",
                "source",
                "first_seen",
                "last_seen",
                "emailed",
            ]
        )
        for r in rows:
            writer.writerow(list(r))
