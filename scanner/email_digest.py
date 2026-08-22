"""Render the daily digest as HTML and send it via Gmail SMTP (app password).

Secrets come from env (set as GitHub repo secrets in the workflow):
    GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT

Why the HTML looks the way it does
----------------------------------
Mail clients are not browsers. The layout is nested tables rather than flex or grid,
every style is inline (Gmail strips <style> blocks), fonts are a system stack (web fonts
do not load), and each gradient sits on a `bgcolor` so clients that ignore
`linear-gradient` still get a solid colour. Job titles carry dir="auto" so the Hebrew
postings render correctly inside the left-to-right layout.
"""

import os
import smtplib
from collections import defaultdict
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Gmail clips any message body over roughly 102 KB. Full cards cost ~1.1 KB each and
# compact rows ~0.23 KB, so we card the first MAX_CARDS, list the next MAX_LISTED, and
# only count the rest. These two ceilings keep any digest under the limit.
MAX_CARDS = 50
MAX_LISTED = 120

# Leads the subject line and the masthead. Set to "" to fall back to plain wording.
DEDICATION = "Job scanner for the most beautiful girl in the world"

# One place to retheme the whole email.
VIOLET = "#7C3AED"
PINK = "#EC4899"
GRADIENT = f"linear-gradient(135deg, {VIOLET} 0%, #A855F7 45%, {PINK} 100%)"
GROUND = "#FBF7FF"
CARD = "#FFFFFF"
BORDER = "#EFE4FB"
INK = "#1F1235"
MUTED = "#7C7391"
PILL_BG = "#FCEEF7"
PILL_INK = "#B83E8C"

FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)


def _preheader(text):
    """Hidden line the inbox shows next to the subject."""
    return (
        f"<div style='display:none;font-size:1px;color:{GROUND};line-height:1px;"
        f"max-height:0;max-width:0;opacity:0;overflow:hidden'>{escape(text)}</div>"
    )


# Per-card styles are hoisted into constants because they repeat once per posting, and
# Gmail clips any message over roughly 102 KB. A 100-job digest is close to that line.
_CARD_TBL = (
    f"width='100%' cellpadding='0' cellspacing='0' border='0' role='presentation' "
    f"style='background:{CARD};border:1px solid {BORDER};border-radius:12px;"
    f"margin:0 0 10px;font-family:{FONT}'"
)
_TITLE_ST = (
    f"font-size:16px;font-weight:600;color:{INK};line-height:1.35;margin:0 0 10px"
)
_PILL_ST = (
    f"display:inline-block;background:{PILL_BG};color:{PILL_INK};font-size:12px;"
    "font-weight:600;padding:4px 10px;border-radius:20px;white-space:nowrap"
)
_BTN_ST = (
    f"display:inline-block;padding:9px 18px;background:{VIOLET};color:#FFFFFF;"
    "font-size:13px;font-weight:600;text-decoration:none;border-radius:8px;"
    "white-space:nowrap"
)


def _job_card(job):
    """One posting: title, location pill, and a tappable button."""
    title = escape(job.get("title") or "Untitled role")
    url = escape(job.get("url") or "#")
    location = (job.get("location") or "").strip()

    pill = ""
    if location and not location.startswith("http"):
        pill = f"<span style='{_PILL_ST}'>{escape(location)}</span>"

    return (
        f"<table {_CARD_TBL}><tr><td style='padding:14px 16px'>"
        f"<div dir='auto' style='{_TITLE_ST}'>{title}</div>"
        "<table width='100%' cellpadding='0' cellspacing='0' border='0' "
        f"role='presentation'><tr><td align='left'>{pill}</td>"
        f"<td align='right'><a href='{url}' style='{_BTN_ST}'>View job &rarr;</a>"
        "</td></tr></table></td></tr></table>"
    )


def _overflow_block(jobs):
    """Compact one-line links for anything past MAX_CARDS."""
    if not jobs:
        return ""
    listed, hidden = jobs[:MAX_LISTED], max(0, len(jobs) - MAX_LISTED)
    rows = "".join(
        f"<div style='margin:0 0 7px'>"
        f"<a href='{escape(j.get('url') or '#')}' dir='auto' style='color:{INK};"
        f"font-size:14px;font-weight:600;text-decoration:none'>"
        f"{escape(j.get('title') or 'Untitled role')}</a>"
        f"<span style='color:{MUTED};font-size:13px'> &middot; "
        f"{escape(j.get('company') or '')}</span></div>"
        for j in listed
    )
    if hidden:
        rows += (
            f"<div style='color:{MUTED};font-size:13px;margin:12px 0 0'>"
            f"and {hidden} more not listed here &mdash; see jobs.csv in the repo.</div>"
        )
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' border='0' "
        f"role='presentation' style='margin:26px 0 4px;font-family:{FONT}'>"
        f"<tr><td style='border-top:1px solid {BORDER};padding:18px 0 0'>"
        f"<div style='font-size:15px;font-weight:700;color:{VIOLET};margin:0 0 12px'>"
        f"{len(jobs)} more role{'s' if len(jobs) != 1 else ''}</div>"
        f"{rows}</td></tr></table>"
    )


def _company_block(company, jobs):
    """A company heading with a count badge, then its postings."""
    count = len(jobs)
    heading = (
        "<table width='100%' cellpadding='0' cellspacing='0' border='0' "
        f"role='presentation' style='margin:22px 0 10px;font-family:{FONT}'><tr>"
        f"<td align='left' style='font-size:15px;font-weight:700;color:{VIOLET};"
        f"letter-spacing:0.2px'>{escape(company)}</td>"
        f"<td align='right' style='font-size:12px;font-weight:600;color:{MUTED}'>"
        f"{count} role{'s' if count != 1 else ''}</td></tr></table>"
    )
    return heading + "".join(_job_card(j) for j in jobs)


def _shell(inner, preheader_text):
    """Wrap the body in the page ground and the 620px column."""
    return (
        f"<div style='background:{GROUND};padding:28px 12px;margin:0'>"
        + _preheader(preheader_text)
        + "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "border='0' style='max-width:620px;margin:0 auto'>" + inner + "</table></div>"
    )


def _header(date_str, count):
    """Gradient masthead. bgcolor carries clients that ignore the gradient."""
    headline = (
        f"{count} new role{'s' if count != 1 else ''}"
        if count
        else "No new roles today"
    )
    title = DEDICATION or "Job Scanner"

    return (
        f"<tr><td bgcolor='{VIOLET}' style='background-image:{GRADIENT};"
        "border-radius:16px 16px 0 0;padding:30px 26px 26px'>"
        # Not uppercased: the dedication is a sentence, and shouting it reads wrong.
        f"<div style='font-family:{FONT};font-size:13px;font-weight:600;"
        f"letter-spacing:0.3px;color:#F3E8FF;margin:0 0 10px'>{escape(title)}</div>"
        f"<div style='font-family:{FONT};font-size:30px;font-weight:700;"
        f"color:#FFFFFF;line-height:1.15;margin:0'>{escape(headline)}</div>"
        f"<div style='font-family:{FONT};font-size:14px;color:#F3E8FF;"
        f"margin:8px 0 0'>{escape(date_str)}</div></td></tr>"
    )


def _footer():
    return (
        f"<tr><td style='background:{CARD};border-radius:0 0 16px 16px;"
        f"border-top:1px solid {BORDER};padding:18px 26px 22px'>"
        f"<div style='font-family:{FONT};font-size:11px;color:{MUTED};"
        "line-height:1.6;margin:0'>"
        "Product &middot; project &middot; operations &middot; coordination &middot; "
        "creative &middot; brand &middot; marketing<br>"
        "Israel only &middot; excludes senior and technical roles &middot; "
        "posted in the last 45 days"
        "</div></td></tr>"
    )


def render_html(jobs, date_str):
    """Build the digest: a gradient masthead, then one card per posting by company."""
    if not jobs:
        body = (
            f"<tr><td style='background:{CARD};padding:30px 26px'>"
            f"<div style='font-family:{FONT};font-size:15px;color:{INK};"
            "line-height:1.6;margin:0'>Nothing new came up today.</div>"
            f"<div style='font-family:{FONT};font-size:14px;color:{MUTED};"
            "line-height:1.6;margin:8px 0 0'>The scanner checked every company on "
            "the list and found no postings it had not already sent you. "
            "Next update tomorrow.</div>"
            "</td></tr>"
        )
        return _shell(
            _header(date_str, 0) + body + _footer(),
            f"No new roles today, {date_str}",
        )

    by_company = defaultdict(list)
    for job in jobs:
        by_company[job.get("company") or "Other"].append(job)

    # Cards are ~1.1 KB each and Gmail clips past ~102 KB, so past MAX_CARDS the rest
    # become one-line links. Only a backlog digest ever reaches this.
    carded, overflow, budget = [], [], MAX_CARDS
    for company in sorted(by_company):
        company_jobs = by_company[company]
        if budget >= len(company_jobs):
            carded.append((company, company_jobs))
            budget -= len(company_jobs)
        else:
            overflow.extend(company_jobs)

    blocks = "".join(_company_block(c, js) for c, js in carded)
    blocks += _overflow_block(overflow)
    body = f"<tr><td style='background:{CARD};padding:4px 20px 20px'>{blocks}</td></tr>"

    companies = len(by_company)
    preheader = (
        f"{len(jobs)} new role{'s' if len(jobs) != 1 else ''} across "
        f"{companies} compan{'ies' if companies != 1 else 'y'}"
    )
    return _shell(_header(date_str, len(jobs)) + body + _footer(), preheader)


def send_email(html_body, subject, *, text_body=None, dry_run=False):
    """Send via Gmail SMTP as multipart/alternative. In dry_run, print instead."""
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
    # The subject holds non-ASCII characters, so it needs RFC 2047 encoding or it
    # arrives as mojibake.
    msg["Subject"] = Header(subject, "utf-8").encode()
    msg["From"] = sender
    msg["To"] = recipient
    # Order matters: clients show the LAST part they can render.
    msg.attach(
        MIMEText(
            text_body or "Open this email in a client that shows HTML.",
            "plain",
            "utf-8",
        )
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def render_text(jobs, date_str):
    """Plain-text alternative, for clients that will not render HTML."""
    if not jobs:
        return f"No new roles today ({date_str})."
    by_company = defaultdict(list)
    for job in jobs:
        by_company[job.get("company") or "Other"].append(job)
    lines = [f"{len(jobs)} new roles - {date_str}", ""]
    for company in sorted(by_company):
        lines.append(company)
        for job in by_company[company]:
            location = (job.get("location") or "").strip()
            suffix = (
                f" ({location})" if location and not location.startswith("http") else ""
            )
            lines.append(f"  - {job.get('title', '')}{suffix}")
            lines.append(f"    {job.get('url', '')}")
        lines.append("")
    return "\n".join(lines)


def subject_for(jobs, date_str):
    """Dedication first, then a part that changes daily.

    The changing tail is not decoration: Gmail threads messages that share a subject, so
    a fixed subject would collapse every digest into one conversation.
    """
    n = len(jobs)
    what = f"{n} new role{'s' if n != 1 else ''}" if n else "No new roles"
    if DEDICATION:
        return f"{DEDICATION} · {what} · {date_str}"
    return f"{what} — {date_str}"
