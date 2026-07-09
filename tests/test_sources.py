"""Tests for source normalization, mainly the Federal Register item mapping
that feeds deadline flags and update detection."""

from fedwatch import sources


FR_DOC = {
    "document_number": "2026-12345",
    "title": "Proposed cap on research project grants",
    "abstract": "NIH proposes...",
    "html_url": "https://www.federalregister.gov/d/2026-12345",
    "publication_date": "2026-07-08",
    "type": "Proposed Rule",
    "comments_close_on": "2026-09-08",
    "effective_on": None,
    "docket_ids": ["NIH-2026-0034"],
    "regulations_dot_gov_url": "https://www.regulations.gov/commenton/NIH-2026-0034-0001",
}


def test_fr_item_maps_structured_fields():
    it = sources._fr_item(FR_DOC, "National Institutes of Health")
    assert it["id"] == "fr-2026-12345"
    assert it["comment_due"] == "2026-09-08"
    assert it["docket"] == "NIH-2026-0034"
    assert it["comment_url"].startswith("https://www.regulations.gov/")
    assert it["comment_opportunity"] is True


def test_fr_item_proposed_rule_is_comment_opportunity_even_without_close_date():
    doc = dict(FR_DOC, comments_close_on=None, regulations_dot_gov_url=None,
               docket_ids=[])
    it = sources._fr_item(doc, "NIH")
    assert it["comment_opportunity"] is True
    assert it["comment_due"] == ""
    assert it["docket"] == ""


def test_fr_item_plain_notice_is_not_comment_opportunity():
    doc = dict(FR_DOC, type="Notice", comments_close_on=None)
    it = sources._fr_item(doc, "NIH")
    assert it["comment_opportunity"] is False
