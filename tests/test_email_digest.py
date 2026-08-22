"""Digest rendering tests.

The style-attribute tests exist because of a real bug: font stacks were written with
quoted family names ('Segoe UI') inside single-quoted style attributes, which closed each
attribute at the first apostrophe and silently dropped every declaration after it. The
email still rendered, just with most of its CSS missing — the failure mode is invisible
unless something checks.
"""

from html.parser import HTMLParser

import pytest

from scanner import email_digest

JOBS = [
    {
        "company": "Moon Active",
        "title": "Product Economy Manager",
        "location": "Tel Aviv",
        "url": "https://jobs.ashbyhq.com/moonactive/abc",
    },
    {
        "company": "Guardio",
        "title": "Creative Strategist",
        "location": "Tel-Aviv, Israel",
        "url": "https://www.comeet.com/jobs/guardio/57.000/x",
    },
]


class _StyleCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.styles = []
        self.stray_attrs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "style":
                self.styles.append(value or "")
            # A truncated style attribute leaves the rest of the declarations behind as
            # bare attribute names like "font-weight:700;color:#7c3aed".
            elif ":" in name and name != "xmlns":
                self.stray_attrs.append(name)


def _parse(html):
    p = _StyleCollector()
    p.feed(html)
    return p


def test_font_stacks_have_no_apostrophes():
    assert "'" not in email_digest.FONT
    assert "'" not in email_digest.FONT_DISPLAY


def test_no_style_attribute_is_truncated():
    parsed = _parse(email_digest.render_html(JOBS, "2026-08-22"))
    assert parsed.stray_attrs == []


def test_company_name_is_semantically_bold_and_violet():
    """Bold comes from <strong>, not font-weight, so a client that drops the style
    attribute still renders the emphasis. The colour is the part that needs CSS."""
    html = email_digest.render_html(JOBS, "2026-08-22")
    for job in JOBS:
        assert "<strong style=" in html
        assert f">{job['company']}</strong>" in html
    parsed = _parse(html)
    violet = [s for s in parsed.styles if email_digest.VIOLET.lower() in s.lower()]
    assert violet, "the violet company colour went missing"


def test_font_family_is_the_last_declaration_in_every_style():
    """Defensive ordering. If an attribute is ever truncated again, the colours, sizes
    and weights survive and only the typeface is lost."""
    parsed = _parse(email_digest.render_html(JOBS, "2026-08-22"))
    for style in parsed.styles:
        if "font-family" not in style:
            continue
        after = style.split("font-family:", 1)[1]
        assert ";" not in after, f"font-family is not last in: {style}"


def test_role_title_is_normal_weight_so_the_company_stands_out():
    assert "font-weight:400" in email_digest._TITLE_ST


@pytest.mark.parametrize("count", [0, 1, 2])
def test_renders_without_error_for_small_counts(count):
    html = email_digest.render_html(JOBS[:count], "2026-08-22")
    assert html.startswith("<div")
    assert _parse(html).stray_attrs == []


def test_subject_leads_with_the_dedication_and_varies_by_count():
    one = email_digest.subject_for(JOBS[:1], "2026-08-22")
    two = email_digest.subject_for(JOBS, "2026-08-22")
    assert one.startswith(email_digest.DEDICATION)
    assert one != two, "subjects must differ or Gmail threads the digests together"
    assert "1 new role" in one and "2 new roles" in two
    assert len(two) < 70, "subject truncates on a phone beyond ~70 chars"


def test_empty_digest_still_renders_a_body():
    html = email_digest.render_html([], "2026-08-22")
    assert "No new roles today" in html
    assert _parse(html).stray_attrs == []


def test_overflow_switches_to_compact_rows_past_max_cards(monkeypatch):
    monkeypatch.setattr(email_digest, "MAX_CARDS", 1)
    many = [dict(JOBS[0], company=f"Co {i}", url=f"https://x/{i}") for i in range(6)]
    html = email_digest.render_html(many, "2026-08-22")
    assert "more roles" in html
    assert _parse(html).stray_attrs == []


def test_digest_stays_under_the_gmail_clipping_limit():
    many = [
        dict(JOBS[0], company=f"Co {i // 3}", url=f"https://x/{i}") for i in range(400)
    ]
    html = email_digest.render_html(many, "2026-08-22")
    assert len(html) < 102_400, "Gmail clips bodies over ~102 KB"


def test_plain_text_alternative_lists_every_role():
    text = email_digest.render_text(JOBS, "2026-08-22")
    for job in JOBS:
        assert job["title"] in text
        assert job["url"] in text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a@x.com", ["a@x.com"]),
        ("a@x.com,b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com, b@y.com , c@z.com", ["a@x.com", "b@y.com", "c@z.com"]),
        ("a@x.com;b@y.com", ["a@x.com", "b@y.com"]),
        ("  a@x.com  ", ["a@x.com"]),
        ("a@x.com,,", ["a@x.com"]),
        ("", []),
        (None, []),
    ],
)
def test_recipient_secret_can_hold_several_addresses(raw, expected):
    """sendmail needs a real list; the raw comma-joined string would be treated as one
    malformed address and rejected."""
    assert email_digest.parse_recipients(raw) == expected
