"""ATS fetchers. One function per provider; all return a list of normalized Job dicts.

Each fetcher isolates its own network/parse errors and returns (jobs, error) so a single
dead company slug never aborts the whole daily run. Field mappings were verified against
live endpoints (see DESIGN.md for the confirmed shapes).

A normalized Job is:
    {
        "job_uid":  "<source>:<board_id>",   # dedup key
        "title":    str,
        "company":  str,
        "location": str,                      # raw location text
        "country":  str | None,               # ISO-ish code when the provider gives one
        "url":      str,
        "source":   str,
    }
"""

import datetime
import hashlib

import requests

UA = {"User-Agent": "Mozilla/5.0 (job-scanner; +https://github.com/job-scanner)"}
TIMEOUT = 30


def _uid(source, board_id, company, title, location):
    """Stable dedup id. Prefer the board's own id; fall back to a content hash."""
    if board_id:
        return f"{source}:{board_id}"
    digest = hashlib.sha1(f"{company}|{title}|{location}".encode()).hexdigest()[:16]
    return f"{source}:{digest}"


def _iso_from_ms(ms):
    """Lever gives epoch milliseconds. Return an ISO date string, or None."""
    if not ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            ms / 1000, datetime.UTC
        ).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _workday_posted(text):
    """Workday gives fuzzy text ('Posted 30+ Days Ago', 'Posted Today'). We can't get an
    exact date, so return a sentinel we can age-check: 'STALE' if it clearly says 30+ days,
    else None (unknown -> kept by the age filter's keep-if-unknown rule)."""
    t = (text or "").lower()
    if "30+" in t or "30 +" in t:
        return "STALE"
    return None


def fetch_greenhouse(company):
    """company: {name, slug}. GET boards-api greenhouse."""
    slug = company["slug"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        jobs.append(
            {
                "job_uid": _uid(
                    "greenhouse", j.get("id"), company["name"], j.get("title"), loc
                ),
                "title": j.get("title", ""),
                "company": company["name"],
                "location": loc,
                "country": None,
                "url": j.get("absolute_url", ""),
                "posted_at": j.get("first_published") or j.get("updated_at"),
                "source": "greenhouse",
            }
        )
    return jobs


def fetch_lever(company):
    """company: {name, slug}. GET lever postings json."""
    slug = company["slug"]
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json():
        cats = j.get("categories") or {}
        loc = cats.get("location", "")
        jobs.append(
            {
                "job_uid": _uid(
                    "lever", j.get("id"), company["name"], j.get("text"), loc
                ),
                "title": j.get("text", ""),
                "company": company["name"],
                "location": loc,
                "country": None,
                "url": j.get("hostedUrl", ""),
                "posted_at": _iso_from_ms(j.get("createdAt")),
                "source": "lever",
            }
        )
    return jobs


def fetch_comeet(company):
    """company: {name, uid, token}. GET comeet careers-api (needs uid + per-company token)."""
    uid = company["uid"]
    token = company["token"]
    url = (
        f"https://www.comeet.com/careers-api/2.0/company/{uid}/positions?token={token}"
    )
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json():
        loc = j.get("location") or {}
        country = loc.get("country")
        loc_text = loc.get("name", "")
        jobs.append(
            {
                "job_uid": _uid(
                    "comeet", j.get("uid"), company["name"], j.get("name"), loc_text
                ),
                "title": j.get("name", ""),
                "company": company["name"],
                "location": loc_text,
                "country": country,
                "url": j.get("url_active_page") or j.get("position_url", ""),
                "posted_at": j.get("time_published") or j.get("time_updated"),
                "source": "comeet",
            }
        )
    return jobs


def fetch_smartrecruiters(company):
    """company: {name, slug}. GET smartrecruiters postings, paginated."""
    slug = company["slug"]
    jobs = []
    offset = 0
    limit = 100
    while True:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
            f"?limit={limit}&offset={offset}"
        )
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])
        for j in content:
            loc = j.get("location") or {}
            country = loc.get("country")
            loc_text = loc.get("fullLocation") or loc.get("city", "")
            job_id = j.get("id")
            jobs.append(
                {
                    "job_uid": _uid(
                        "smartrecruiters",
                        job_id,
                        company["name"],
                        j.get("name"),
                        loc_text,
                    ),
                    "title": j.get("name", ""),
                    "company": company["name"],
                    "location": loc_text,
                    "country": country,
                    "url": f"https://jobs.smartrecruiters.com/{slug}/{job_id}",
                    "posted_at": j.get("releasedDate"),
                    "source": "smartrecruiters",
                }
            )
        offset += limit
        if offset >= data.get("totalFound", 0) or not content:
            break
    return jobs


def fetch_workday(company):
    """company: {name, tenant, site, wd_host}. POST workday cxs jobs, paginated.

    Uses searchText='Israel' to pre-filter server-side (Workday tenants are huge).
    """
    tenant = company["tenant"]
    site = company["site"]
    wd_host = company.get("wd_host", "wd5")
    base = f"https://{tenant}.{wd_host}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    headers = {**UA, "Content-Type": "application/json", "Accept": "application/json"}
    jobs = []
    offset = 0
    limit = 20
    while True:
        payload = {
            "limit": limit,
            "offset": offset,
            "searchText": company.get("search_text", "Israel"),
            "appliedFacets": {},
        }
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        postings = data.get("jobPostings", [])
        for j in postings:
            path = j.get("externalPath", "")
            loc = j.get("locationsText", "")
            jobs.append(
                {
                    "job_uid": _uid(
                        "workday", path, company["name"], j.get("title"), loc
                    ),
                    "title": j.get("title", ""),
                    "company": company["name"],
                    "location": loc,
                    "country": None,
                    "url": f"{base}/{site}{path}" if path else base,
                    "posted_at": _workday_posted(j.get("postedOn")),
                    "source": "workday",
                }
            )
        offset += limit
        if offset >= data.get("total", 0) or not postings:
            break
    return jobs


def fetch_ashby(company):
    """company: {name, slug}. GET ashby public job-board API."""
    slug = company["slug"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        loc = j.get("location", "") or ""
        postal = (j.get("address") or {}).get("postalAddress") or {}
        country = postal.get("addressCountry")
        jobs.append(
            {
                "job_uid": _uid(
                    "ashby", j.get("id"), company["name"], j.get("title"), loc
                ),
                "title": j.get("title", ""),
                "company": company["name"],
                "location": loc,
                "country": country,
                "url": j.get("jobUrl") or j.get("applyUrl", ""),
                "posted_at": j.get("publishedAt"),
                "source": "ashby",
            }
        )
    return jobs


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "comeet": fetch_comeet,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
    "ashby": fetch_ashby,
}


def fetch_company(company):
    """Dispatch to the right fetcher by company['source']. Returns (jobs, error_str).

    Never raises: a failing company yields ([], "<reason>") so the daily run continues.
    """
    source = company.get("source")
    fetcher = FETCHERS.get(source)
    if fetcher is None:
        return [], f"unknown source '{source}'"
    try:
        return fetcher(company), None
    except requests.HTTPError as e:
        return [], f"http {e.response.status_code}"
    except requests.RequestException as e:
        return [], f"network: {type(e).__name__}"
    except (KeyError, ValueError) as e:
        return [], f"parse: {type(e).__name__}: {e}"
