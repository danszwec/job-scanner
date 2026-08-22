"""Title role matching (English + Hebrew) and the Israel location rule.

A job passes the filter when:
  1. its title names a role in the target families (see title_matches), AND
  2. its title contains none of the EXCLUDE (seniority / other-field) terms, AND
  3. it is located in Israel (see is_israel), AND
  4. it was posted within MAX_AGE_DAYS (see is_fresh).

Matching a role, not a keyword
------------------------------
An earlier version listed bare words — "manager", "product", "ops" — and accepted any
title containing one. That let through every engineering, tax and payroll title that
happens to use the word ("Software Engineering Manager", "Tax Manager", "Ops Data
Engineer"). We instead require a ROLE: a DOMAIN word (product / project / operations /
brand / marketing ...) next to a HEAD noun (manager / coordinator / designer ...), in
either order. "Engineering Manager" has a head but no domain, so it drops out; "Software
Project Manager" has both, so it stays.

Because engineer / developer / architect / scientist are deliberately NOT head nouns, most
technical titles fail on structure alone and need no blocklist.

A few terms are strong enough on their own (coordinator, copywriter, art director) and are
matched without needing a domain word. Hebrew works the same way, with its own head and
domain lists; Hebrew has no casing, so it is matched as substrings to absorb the
מנהל/מנהלת gender suffixes.
"""

import datetime
import re

# --- Roles we want (see DESIGN.md) --------------------------------------------------

# The subject area of the job.
DOMAINS_EN = [
    "product",
    "project",
    r"program(me)?",
    "portfolio",
    r"operations?",
    "ops",
    r"brand(ing)?",
    "marketing",
    "creative",
    "content",
    "community",
    "social media",
    "campaign",
    r"events?",
    "studio",
    "production",
    r"partner(ship)?s?",
    "business development",
    "account",
    "customer success",
    "customer experience",
    "growth",
    # Only the marketing sense of "acquisition" — bare "acquisition" pulled in every
    # "Talent Acquisition" recruiting role.
    r"(?:user|customer|player) acquisition",
    "demand generation",
    "facilities",
    "office",
    "procurement",
    "logistics",
    "supply chain",
    "delivery",
]

# The kind of role. Note what is absent: engineer, developer, architect, scientist, sre,
# qa. Leaving them out is what keeps technical titles from matching.
HEADS_EN = [
    "manager",
    "mgr",
    r"coordinators?",
    "owner",
    "director",
    "specialist",
    "planner",
    "producer",
    "strategist",
    "designer",
    "associate",
    "analyst",
    "generalist",
    "administrator",
    "officer",
    "consultant",
    "lead",
    "head",
]
# Deliberately not heads: "executive" (Account Executive is quota sales) and "partner"
# (People Partner / Talent Acquisition Partner are HR). Both still work as domain words,
# so "Partner Development Manager" is unaffected.

# Strong enough to match with no domain word beside them.
STANDALONE_EN = [
    r"coordinat(or|ion)",
    "copywriter",
    "creative",
    "art director",
    "branding",
    r"product management",
    r"project management",
    "scrum master",
]

DOMAINS_HE = [
    "מוצר",  # product
    "פרויקט",  # project
    "פרוייקט",  # project (alt spelling)
    "מיזם",  # venture / initiative
    "תפעול",  # operations
    "מותג",  # brand
    "מיתוג",  # branding
    "שיווק",  # marketing
    "תוכן",  # content
    "קריאייטיב",  # creative
    "יצירתי",  # creative
    "קמפיין",  # campaign
    "אירוע",  # event
    "קהילה",  # community
    "לקוחות",  # clients
    "רכש",  # procurement
    "לוגיסטיק",  # logistics
    "משאבי אנוש",  # HR
]

HEADS_HE = [
    "מנהל",  # manager (מנהל/מנהלת)
    "רכז",  # coordinator (רכז/רכזת)
    "מתאם",  # coordinator
    "מתאמת",
    "מפיק",  # producer
    "מפיקה",
    "אחראי",  # in charge of
    "אחראית",
    "ניהול",  # management
]

# Hebrew terms strong enough on their own.
STANDALONE_HE = [
    "רכז",  # coordinator — a role name by itself
    "רכזת",
    "תיאום",  # coordination
    "קופירייט",  # copywriting
    "מיתוג",  # branding
]

# --- Roles we do NOT want -----------------------------------------------------------

# Seniority. The old list held only "senior" and "lead", so "Sr Staff Inbound Product
# Manager" and "Principal Product Manager" both slipped through. "director" is
# deliberately NOT here: art director and creative director are target roles.
EXCLUDE_EN = [
    "senior",
    "sr",
    "snr",
    "staff",
    "principal",
    "lead",
    "leader",
    "head of",
    "vp",
    "svp",
    "evp",
    "chief",
]

# Other professions that can still borrow a domain word ("Client and Collections
# Coordinator", "Product Counsel"). Structure catches most of these already; this is a
# backstop.
EXCLUDE_FIELD_EN = [
    "tax",
    "audit",
    "auditor",
    "payroll",
    "bookkeep(er|ing)",
    "accountant",
    "actuar(y|ial)",
    "controller",
    "collections",
    "counsel",
    "attorney",
    "paralegal",
    "physician",
    r"nurse",
    "veterinar(y|ian)",
    "pharmacist",
]

EXCLUDE_HE = [
    "בכיר",  # senior (בכיר/בכירה)
    "מוביל",  # lead (מוביל/מובילה)
    "ראש צוות",  # team lead
    "סמנכ",  # deputy VP
    "מנכ",  # CEO
    "סוציאלי",  # social worker — different profession
    "שליח",  # emissary — different profession
    'רו"ח',  # CPA
    "מבקר",  # auditor
]


def _group(words):
    return "(?:" + "|".join(words) + ")"


# Up to a few filler words may sit between the domain and the head, so "Product Marketing
# Manager" and "Director of Product Design" both match.
_FILLER = r"[\w&/,'’\-\.\(\)]*(?:\s+[\w&/,'’\-\.\(\)]+){0,3}?\s+"

_ROLE_EN_RE = re.compile(
    r"\b" + _group(DOMAINS_EN) + r"\b" + _FILLER + r"\b" + _group(HEADS_EN) + r"\b"
    r"|"
    r"\b" + _group(HEADS_EN) + r"\b" + _FILLER + r"\b" + _group(DOMAINS_EN) + r"\b",
    re.IGNORECASE,
)
_STANDALONE_EN_RE = re.compile(r"\b" + _group(STANDALONE_EN) + r"\b", re.IGNORECASE)
_EXCLUDE_EN_RE = re.compile(
    r"\b" + _group(EXCLUDE_EN + EXCLUDE_FIELD_EN) + r"\b", re.IGNORECASE
)


def _has_include(title):
    if _STANDALONE_EN_RE.search(title) or _ROLE_EN_RE.search(title):
        return True
    if any(w in title for w in STANDALONE_HE):
        return True
    has_domain = any(w in title for w in DOMAINS_HE)
    has_head = any(w in title for w in HEADS_HE)
    return has_domain and has_head


def _has_exclude(title):
    if _EXCLUDE_EN_RE.search(title):
        return True
    return any(root in title for root in EXCLUDE_HE)


def title_matches(title):
    """True iff the title names a target role and carries no excluded term."""
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
