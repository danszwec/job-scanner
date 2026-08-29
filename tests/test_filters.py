"""Filter tests. Every title here is a real posting seen in a live scan on 2026-08-21.

The KEEP / DROP split encodes the target profile: product, project, programme,
operations, coordination, creative, brand and marketing roles, excluding senior and
technical ones. When the profile changes, change these lists first.
"""

import datetime

import pytest

from scanner import filters

# --- titles that must pass -----------------------------------------------------------

KEEP = [
    "Product Manager - Agentic AI",
    "Product Manager , Developer Experience",
    "IS Product Manager",
    "Product Marketing Manager- Retail & CPG Industry",
    "Product Economy Manager",
    "Product Monetization Manager",
    "Product Growth Manager",
    "Software Project Manager",
    "AI Project Manager",
    "Hardware Project Manager",
    "Technical Program Manager",
    "Sales Program Manager",
    "Program Manager - CTO Office (Maternity Leave Replacement)",
    "Global Revenue Operations Project manager",
    "Operation Manager (Temp) - Channels",
    "Operations Manager, Oasis",
    "Growth Operations Manager - Temporary Position",
    "Outbound Marketing Operations Manager",
    "Programmatic Operations Manager- Temp",
    "Ad Ops Manager",
    "Facilities Operations Specialist",
    "People Operations Specialist - Maternity Leave Coverage",
    "Office & Operations Manager",
    "Commercial Operations Analyst",
    "Marketing Coordinator",
    "Influencer & PR Coordinator",
    "Israel Service Logistics Coordinator",
    "Brand Designer",
    "Marketing & Brand Designer - Maternity Cover",
    "Product Designer",
    "Director of Product Design",
    "Creative Strategist - Maternity Leave Replacement / Contractor",
    "Art Director",
    "Marketing Manager",
    "B2B Demand Generation Manager",
    "Marketing Data Analyst",
    "Mobile User Acquisition Manager",
    "מנהל/ת מיזם מעגל משפחתי",
    "רכז/ת תפעול צפון",
    "רכז/ת פרויקט דילר שותפות אשקלון - בולטימור - 75% משרה",
    "מנהל/ת פרויקטים",
]

# --- titles that must NOT pass -------------------------------------------------------

DROP_TECHNICAL = [
    "Software Engineering Manager",
    "Engineering Manager, AP",
    "Engineering Manager",
    "Performance Engineering Manager",
    "Sales Engineering Manager",
    "Backend Team manager",
    "Infrastructure Group manager",
    "Ops Data Engineer",
    "DevOps Operations Engineer",
    "Product Security Engineer",
    "Product Security Architect- 9-month temp position",
    "Data Engineer (Product & Customer Insights)",
    "Staff Software Engineer - Product Security",
    "Manager, Cyber Research",
    "Back End Developer",
    "Unity Developer",
    "AI Developer",
]

DROP_OTHER_FIELD = [
    "Tax Manager",
    "US Tax Manager",
    "International Tax Manager",
    "Indirect Tax Manager",
    "Audit Manager",
    "Export Audit Manager",
    "Audit, SOX & Controls Manager  - Financial Sector",
    "Payroll Manager",
    "Treasury Manager",
    "Strategic FP&A Manager",
    "Financial Controller",
    "Legal Counsel",
    "Client and Collections Coordinator",
    "עובד/ת סוציאלי/ת - מרכז קליטה כרמיאל",
    "שליח ושליחת יהדות - פרויקט גיור עולי אתיופיה",
]

# Recruiting and quota-carrying sales are separate job families. These leaked in when
# "talent"/"acquisition" were domain words and "partner"/"executive" were head nouns.
DROP_ADJACENT_FAMILIES = [
    "Talent Acquisition Specialist",
    "Talent Acquisition Associate",
    "Talent Acquisition Partner",
    "Talent Acquisition Business Partner (Maternity Leave Cover)",
    "People Partner",
    "Technology Procurement Business Partner",
    "Account Executive",
    "Account Executive - EMEA",
    "Account Executive- Defense Sector",
    "Enterprise Account Executive (TLV)",
    "Client Enablement Associate",
    # Account management and customer success: a different job family, excluded on
    # 2026-08-29 once they turned out to be the biggest remaining source of noise.
    "Account Manager",
    "Major Account Manager",
    "SMB Account Manager",
    "Technical Account Manager",
    "Programatic account Manager- Maternity Leave Cover)",
    "Advertiser Account Manager (Domestic Market)",
    "Customer Success Manager",
    "Enterprise Customer Success Manager",
    "Technical Customer Success Manager, Endpoint Security",
    "Junior Client Success Manager",
    "Customer Experience Specialist",
    "Customer Experience Associate",
]

DROP_SENIORITY = [
    "Sr Staff Inbound Product Manager",
    "Staff Growth Product Manager",
    "Principal Product Manager, Core AI",
    "Senior Product Manager",
    "Head of Brand",
    "VP Product",
    "Chief Product Officer",
    "Product Manager Team Lead",
    "מנהל/ת מוצר בכיר/ה",
]


@pytest.mark.parametrize("title", KEEP)
def test_target_roles_pass(title):
    assert filters.title_matches(title) is True


@pytest.mark.parametrize("title", DROP_TECHNICAL)
def test_technical_roles_dropped(title):
    assert filters.title_matches(title) is False


@pytest.mark.parametrize("title", DROP_OTHER_FIELD)
def test_other_professions_dropped(title):
    assert filters.title_matches(title) is False


@pytest.mark.parametrize("title", DROP_ADJACENT_FAMILIES)
def test_recruiting_and_sales_roles_dropped(title):
    assert filters.title_matches(title) is False


@pytest.mark.parametrize("title", DROP_SENIORITY)
def test_senior_roles_dropped(title):
    assert filters.title_matches(title) is False


def test_empty_title_does_not_pass():
    assert filters.title_matches("") is False
    assert filters.title_matches(None) is False


# --- location rule -------------------------------------------------------------------


@pytest.mark.parametrize(
    "job,company_is_israeli,expected",
    [
        ({"country": "il", "location": "Anywhere"}, False, True),
        ({"country": "United States", "location": "Tel Aviv"}, True, False),
        ({"country": None, "location": "Tel Aviv-Yafo, Israel"}, True, True),
        ({"country": None, "location": "Herzliya"}, True, True),
        ({"country": None, "location": "Bangkok, Thailand"}, True, False),
        ({"country": None, "location": "New York, New York"}, True, False),
        ({"country": None, "location": "Remote"}, True, True),
        ({"country": None, "location": "Remote"}, False, False),
        ({"country": None, "location": ""}, True, True),
        (
            {"country": None, "location": "", "url": "/job/Israel-Yokneam/x"},
            False,
            True,
        ),
    ],
)
def test_is_israel(job, company_is_israeli, expected):
    job.setdefault("url", "")
    assert filters.is_israel(job, company_is_israeli=company_is_israeli) is expected


# --- freshness rule ------------------------------------------------------------------

NOW = datetime.datetime(2026, 8, 21, tzinfo=datetime.UTC)


@pytest.mark.parametrize(
    "posted_at,expected",
    [
        ("2026-08-20T10:00:00Z", True),
        ("2026-07-20T10:00:00Z", True),
        ("2026-06-01T10:00:00Z", False),
        ("STALE", False),
        (None, True),
        ("not-a-date", True),
        ("2026-08-17T04:53:25-04:00", True),
    ],
)
def test_is_fresh(posted_at, expected):
    assert filters.is_fresh({"posted_at": posted_at}, now=NOW) is expected


def test_passes_requires_all_three_rules():
    job = {
        "title": "Product Manager",
        "location": "Tel Aviv, Israel",
        "country": None,
        "url": "",
        "posted_at": "2026-08-20T10:00:00Z",
    }
    assert filters.passes(job) is True
    assert filters.passes({**job, "title": "Software Engineer"}) is False
    assert filters.passes({**job, "location": "Berlin, Germany"}) is False
    assert filters.passes({**job, "posted_at": "2026-01-01T10:00:00Z"}) is False
