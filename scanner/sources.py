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
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).isoformat()
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


def find_israel_facet(facets):
    """Locate the facet that filters a Workday tenant down to Israel.

    Returns (facet_parameter, value_id), or None if the tenant does not expose one.

    Tenants disagree on where location lives. Salesforce puts a country facet at the top
    level; Nvidia and Intel nest theirs a group deep under 'locationMainGroup', and the
    parameter to send back is the one on the *inner* group, not the outer one. So we walk
    the tree instead of hardcoding ids — which also means a tenant reorganising its
    facets degrades to the old search instead of silently returning nothing.
    """

    def walk(param, values):
        for value in values or []:
            nested = value.get("values")
            if nested:
                found = walk(value.get("facetParameter") or param, nested)
                if found:
                    return found
            elif "israel" in str(value.get("descriptor", "")).lower():
                return param, value.get("id")
        return None

    for facet in facets or []:
        found = walk(facet.get("facetParameter"), facet.get("values"))
        if found:
            return found
    return None


# A tenant with a huge Israel presence still has to terminate. 20 per page, so this caps
# a single company at 3000 postings.
WORKDAY_MAX_PAGES = 150


def fetch_workday(company):
    """company: {name, tenant, site, wd_host}. POST workday cxs jobs, paginated.

    Filters by the tenant's Israel location facet. The previous approach passed
    searchText='Israel', which is a free-text search over the whole posting rather than a
    location filter: it found 40 of Nvidia's 435 Israeli roles, none of Salesforce's 12,
    and on PayPal 'IL' matched Illinois. Facets are the actual location filter.

    Falls back to searchText when a tenant exposes no Israel facet, so a tenant with no
    Israeli presence still behaves as before.
    """
    tenant = company["tenant"]
    site = company["site"]
    wd_host = company.get("wd_host", "wd5")
    base = f"https://{tenant}.{wd_host}.myworkdayjobs.com"
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    headers = {**UA, "Content-Type": "application/json", "Accept": "application/json"}

    # One probe to read the facet tree, then paginate with the filter applied.
    probe = requests.post(
        url,
        headers=headers,
        json={"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}},
        timeout=TIMEOUT,
    )
    probe.raise_for_status()
    facet = find_israel_facet(probe.json().get("facets"))

    if facet:
        applied_facets = {facet[0]: [facet[1]]}
        search_text = ""
    else:
        applied_facets = {}
        search_text = company.get("search_text", "Israel")

    jobs = []
    offset = 0
    limit = 20
    total = None
    for _ in range(WORKDAY_MAX_PAGES):
        payload = {
            "limit": limit,
            "offset": offset,
            "searchText": search_text,
            "appliedFacets": applied_facets,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        postings = data.get("jobPostings", [])
        # Workday reports `total` on the first page only; later pages say 0. Trusting it
        # every page made `offset >= total` true immediately, which silently capped every
        # Workday company at 40 postings.
        if total is None:
            total = data.get("total") or 0
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
        if not postings or (total and offset >= total):
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


def fetch_workable(company):
    """company: {name, slug}. GET the public widget API.

    The widget endpoint is the only Workable board API that needs no key. It returns
    `locations[].countryCode`, which gives clean Israel filtering.
    """
    slug = company["slug"]
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        locations = j.get("locations") or []
        first = locations[0] if locations else {}
        country = first.get("countryCode") or j.get("country")
        city = j.get("city") or first.get("city") or ""
        loc_text = ", ".join(p for p in (city, j.get("country")) if p)
        jobs.append(
            {
                "job_uid": _uid(
                    "workable",
                    j.get("shortcode"),
                    company["name"],
                    j.get("title"),
                    loc_text,
                ),
                "title": j.get("title", ""),
                "company": company["name"],
                "location": loc_text,
                "country": country,
                "url": j.get("url") or j.get("shortlink", ""),
                "posted_at": j.get("published_on") or j.get("created_at"),
                "source": "workable",
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
    "workable": fetch_workable,
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
