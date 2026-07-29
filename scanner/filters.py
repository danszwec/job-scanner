"""Title keyword matching (English + Hebrew) and the Israel location rule.

A job passes the filter when:
  1. its title contains at least one INCLUDE keyword, AND
  2. its title contains none of the EXCLUDE keywords, AND
  3. it is located in Israel (see is_israel).

All title matching is case-insensitive and word-aware for English (so "product" does not
match inside "productivity" unintentionally we still allow it — see note). Hebrew has no
casing; we match on substrings of the Hebrew roots.
"""

import datetime
import re

# --- Keyword map (see DESIGN.md). English matched as whole words; Hebrew as substrings. ---

INCLUDE_EN = [
    "project",
    "product",
    "manager",
    "coordinat",  # coordinator / coordination
    "creative",
    "operations",
    "ops",
    "brand",
]

INCLUDE_HE = [
    "מוצר",  # product
    "פרויקט",  # project
    "מנהל",  # manager (מנהל/מנהלת)
    "ניהול",  # management
    "רכז",  # coordinator (רכז/רכזת)
    "תיאום",  # coordination
    "קריאייטיב",  # creative
    "יצירתי",  # creative
    "תפעול",  # operations
    "מותג",  # brand
    "מיתוג",  # branding
]

EXCLUDE_EN = ["senior", "lead"]

EXCLUDE_HE = [
    "בכיר",  # senior (בכיר/בכירה)
    "מוביל",  # lead (מוביל/מובילה)
    "ראש צוות",  # team lead
]

# English include words matched on a word boundary at the start (prefix) so "coordinat"
# catches coordinator/coordination and "operations"/"ops" both hit. Exclude words matched
# as whole words to avoid over-excluding.
_INCLUDE_EN_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in INCLUDE_EN) + r")", re.IGNORECASE
)
_EXCLUDE_EN_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in EXCLUDE_EN) + r")\b", re.IGNORECASE
)


def _has_include(title):
    if _INCLUDE_EN_RE.search(title):
        return True
    return any(root in title for root in INCLUDE_HE)


def _has_exclude(title):
    if _EXCLUDE_EN_RE.search(title):
        return True
    return any(root in title for root in EXCLUDE_HE)


def title_matches(title):
    """True iff title has an include keyword and no exclude keyword."""
    if not title:
        return False
    return _has_include(title) and not _has_exclude(title)


# --- Location rule ---

ISRAEL_TERMS = [
    "israel",
    "ישראל",
    "tel aviv",
    "תל אביב",
    "tel-aviv",
    "haifa",
    "חיפה",
    "jerusalem",
    "ירושלים",
    "herzliya",
    "הרצליה",
    "ramat gan",
    "רמת גן",
    "petah tikva",
    "פתח תקווה",
    "netanya",
    "נתניה",
    "beer sheva",
    "be'er sheva",
    "באר שבע",
    "yokneam",
    "יקנעם",
    "raanana",
    "רעננה",
    "rehovot",
    "רחובות",
    "caesarea",
    "kfar saba",
    "or yehuda",
    "airport city",
]

# Clear non-Israel signals: if country code says elsewhere, exclude outright.
_NON_IL_COUNTRY = None  # any country present and != IL/il handled in is_israel


def is_israel(job, company_is_israeli=True):
    """Decide whether a normalized job is located in Israel.

    Israeli companies (Aleph, AppsFlyer, ...) hire globally, so a blocklist of foreign
    cities is hopeless — you can never enumerate every city on earth. We instead REQUIRE
    a positive Israel signal whenever any location text is present:

      - Provider gave a country code -> trust it: 'il' yes, anything else no.
      - Non-empty location text / URL -> include ONLY if it names Israel or an Israeli
        city. A concrete foreign location (Bangkok, Cairo, ...) has no Israel signal, so
        it is excluded. This is the key fix for the "Israeli company, foreign job" leak.
      - Empty / "remote" / genuinely blank -> ambiguous: fall back to company_is_israeli.

    Also checks the URL, since Workday encodes the country in externalPath
    (e.g. /job/Israel-Yokneam/...).
    """
    country = (job.get("country") or "").strip().lower()
    if country:
        return country in ("il", "isr", "israel")

    haystack = f"{job.get('location', '')} {job.get('url', '')}".lower()
    if any(term in haystack for term in ISRAEL_TERMS):
        return True

    # No country code and no Israel signal. If there is a concrete location string, it
    # names somewhere that is not Israel -> exclude. Only truly blank/remote is ambiguous.
    if _has_concrete_location(job.get("location", "")):
        return False

    # Ambiguous / empty / remote-only: fall back to whether the company is Israeli.
    return company_is_israeli


# A "remote"/blank location carries no place signal and stays ambiguous; anything with a
# real place name (comma, or a word that isn't just remote/hybrid/onsite) is concrete.
_NON_PLACE_WORDS = {
    "remote",
    "hybrid",
    "onsite",
    "on-site",
    "anywhere",
    "global",
    "worldwide",
    "",
}


def _has_concrete_location(location_text):
    t = (location_text or "").strip().lower()
    if not t:
        return False
    # Strip common remote/hybrid qualifiers; if a real place name remains, it's concrete.
    cleaned = t.replace("-", " ")
    tokens = [w.strip(" ,()/") for w in cleaned.replace(",", " ").split()]
    meaningful = [w for w in tokens if w and w not in _NON_PLACE_WORDS]
    return bool(meaningful)


MAX_AGE_DAYS = 45


def is_fresh(job, now=None):
    """True if the job was posted within MAX_AGE_DAYS. Unknown date -> kept (True).

    posted_at may be an ISO datetime string, the sentinel 'STALE' (Workday '30+ days'),
    or None. We never want a job that's been open longer than ~6 weeks.
    """
    posted = job.get("posted_at")
    if posted == "STALE":
        return False
    if not posted:
        return True  # unknown age -> keep (avoid hiding a genuinely fresh job)
    try:
        dt = datetime.datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True  # unparseable -> keep
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    now = now or datetime.datetime.now(datetime.UTC)
    return (now - dt).days <= MAX_AGE_DAYS


def passes(job, company_is_israeli=True):
    """Full filter: title keywords + Israel location + posted within MAX_AGE_DAYS."""
    return (
        title_matches(job.get("title", ""))
        and is_israel(job, company_is_israeli)
        and is_fresh(job)
    )
