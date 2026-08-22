"""Source-layer tests. No network: these cover the parsing and pagination logic that
went wrong in ways a live scan did not reveal.
"""

from scanner import sources

# Shapes copied from live responses on 2026-08-22.

SALESFORCE_FACETS = [
    {
        "facetParameter": "jobFamilyGroup",
        "values": [{"descriptor": "Engineering", "id": "abc", "count": 100}],
    },
    {
        "facetParameter": "CF_-_REC_-_LRV_-_Country_from_Job_Posting_Location",
        "values": [
            {"descriptor": "India", "id": "in-id", "count": 300},
            {"descriptor": "Israel", "id": "il-id", "count": 12},
        ],
    },
]

# Nvidia and Intel nest location one group deep, and the parameter to send back is the
# one on the inner group, not on 'locationMainGroup'.
NVIDIA_FACETS = [
    {"facetParameter": "timeType", "values": [{"descriptor": "Full time", "id": "ft"}]},
    {
        "facetParameter": "locationMainGroup",
        "values": [
            {
                "facetParameter": "locationHierarchy2",
                "descriptor": "Location Type",
                "values": [{"descriptor": "Office", "id": "office", "count": 2530}],
            },
            {
                "facetParameter": "locationHierarchy1",
                "descriptor": "Locations",
                "values": [
                    {"descriptor": "India", "id": "india-id", "count": 225},
                    {"descriptor": "Israel", "id": "israel-id", "count": 435},
                ],
            },
        ],
    },
]


def test_finds_a_top_level_country_facet():
    assert sources.find_israel_facet(SALESFORCE_FACETS) == (
        "CF_-_REC_-_LRV_-_Country_from_Job_Posting_Location",
        "il-id",
    )


def test_finds_a_nested_facet_and_returns_the_inner_parameter():
    """The outer 'locationMainGroup' is not a usable filter parameter — sending it
    returns nothing. The inner 'locationHierarchy1' is the one that works."""
    assert sources.find_israel_facet(NVIDIA_FACETS) == (
        "locationHierarchy1",
        "israel-id",
    )


def test_returns_none_when_the_tenant_has_no_israel_facet():
    facets = [
        {
            "facetParameter": "locationHierarchy1",
            "values": [{"descriptor": "Illinois", "id": "il-state", "count": 16}],
        }
    ]
    assert sources.find_israel_facet(facets) is None


def test_illinois_does_not_count_as_israel():
    """PayPal's tenant matched 'IL' to Illinois under the old searchText approach."""
    facets = [
        {
            "facetParameter": "loc",
            "values": [{"descriptor": "IL - Illinois", "id": "x", "count": 16}],
        }
    ]
    assert sources.find_israel_facet(facets) is None


def test_handles_empty_and_missing_facets():
    assert sources.find_israel_facet([]) is None
    assert sources.find_israel_facet(None) is None
    assert sources.find_israel_facet([{"facetParameter": "x"}]) is None


def test_workday_posted_flags_only_the_clearly_old_ones():
    assert sources._workday_posted("Posted 30+ Days Ago") == "STALE"
    assert sources._workday_posted("Posted 30 + Days Ago") == "STALE"
    assert sources._workday_posted("Posted Today") is None
    assert sources._workday_posted("Posted Yesterday") is None
    assert sources._workday_posted(None) is None


def test_uid_prefers_the_board_id_and_falls_back_to_a_content_hash():
    with_id = sources._uid("greenhouse", 12345, "Wix", "Product Manager", "Tel Aviv")
    assert with_id == "greenhouse:12345"

    no_id = sources._uid("greenhouse", None, "Wix", "Product Manager", "Tel Aviv")
    assert no_id.startswith("greenhouse:")
    assert no_id != "greenhouse:None"
    # Same content must hash the same, different content must not collide.
    assert no_id == sources._uid(
        "greenhouse", None, "Wix", "Product Manager", "Tel Aviv"
    )
    assert no_id != sources._uid("greenhouse", None, "Wix", "Product Manager", "Haifa")


def test_iso_from_ms_handles_lever_epochs_and_junk():
    assert sources._iso_from_ms(1756000000000).startswith("2025-")
    assert sources._iso_from_ms(None) is None
    assert sources._iso_from_ms(0) is None
    assert sources._iso_from_ms("not-a-number") is None


def test_unknown_source_is_reported_not_raised():
    jobs, err = sources.fetch_company({"name": "X", "source": "nosuchats"})
    assert jobs == []
    assert "unknown source" in err
