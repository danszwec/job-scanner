"""Render the daily digest as HTML and send it via Gmail SMTP (app password).

Secrets come from env (set as GitHub repo secrets in the workflow):
    GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT
"""

import os
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def render_html(jobs, date_str):
    """Group jobs by company, one linked row each. Plain, clean layout."""
    if not jobs:
        return (
            f"<div style='font-family:Arial,sans-serif;font-size:15px;color:#333'>"
            f"<p>No new jobs today ({escape(date_str)}).</p>"
            f"<p style='color:#888'>The scanner ran and found nothing new matching your "
            f"filters. You'll get the next update tomorrow.</p></div>"
        )

    by_company = defaultdict(list)
    for j in jobs:
        by_company[j["company"]].append(j)

    parts = [
        "<div style='font-family:Arial,sans-serif;font-size:15px;color:#333;max-width:640px'>",
        f"<h2 style='color:#1a1a1a'>{len(jobs)} new job"
        f"{'s' if len(jobs) != 1 else ''} — {escape(date_str)}</h2>",
    ]
    for company in sorted(by_company):
        parts.append(
            f"<h3 style='margin:18px 0 6px;color:#2b5797'>{escape(company)}</h3><ul style='margin:0;padding-left:18px'>"
        )
        for j in by_company[company]:
            title = escape(j["title"])
            url = escape(j["url"])
            loc = escape(j["location"]) if j["location"] else ""
            loc_html = f" <span style='color:#888'>— {loc}</span>" if loc else ""
            parts.append(
                f"<li style='margin:4px 0'><a href='{url}' "
                f"style='color:#2b5797;text-decoration:none'>{title}</a>{loc_html}</li>"
            )
        parts.append("</ul>")
    parts.append(
        "<p style='color:#aaa;font-size:12px;margin-top:24px'>"
        "Automated daily job scan. Filters: product/project/manager/coordination/"
        "creative/operations/brand · excludes senior/lead · Israel only.</p></div>"
    )
    return "".join(parts)


def send_email(html_body, subject, *, dry_run=False):
    """Send via Gmail SMTP. In dry_run, print instead of sending."""
    sender = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("RECIPIENT")

    if dry_run:
        print(f"[DRY RUN] would send to {recipient}\nSubject: {subject}\n")
        print(html_body[:800])
        return

    if not (sender and password and recipient):
        raise RuntimeError(
            "Missing GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT env vars"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def subject_for(jobs, date_str):
    if not jobs:
        return f"No new jobs today — {date_str}"
    n = len(jobs)
    return f"{n} new job{'s' if n != 1 else ''} — {date_str}"
