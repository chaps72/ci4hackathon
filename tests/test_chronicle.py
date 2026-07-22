"""Tests for the historical-record chronicle: significance screen, merge
logic (dedupe, new/existing storylines), and page rendering."""

import fedwatch.emailer as emailer
import send_digest as sd

ITEMS = [
    {"id": "news-1", "type": "News", "source": "News", "level": "HIGH",
     "date": "2026-07-17", "title": "AHRQ ends dozens of grants",
     "url": "https://insidehighered.com/x"},
    {"id": "fr-2", "type": "Notice", "source": "Federal Register", "level": "CRITICAL",
     "date": "2026-07-21", "title": "Notice of termination of certain grants",
     "url": "https://federalregister.gov/y"},
    {"id": "fr-3", "type": "Notice", "source": "Federal Register", "level": "INFO",
     "date": "2026-07-21", "title": "Routine meeting notice", "url": ""},
]


def test_significant_keeps_high_press_and_updates_only():
    got = sd._significant(ITEMS + [{"id": "fr-4", "level": "MODERATE",
                                    "update_note": "Finalizes earlier rule."}])
    ids = [i["id"] for i in got]
    assert ids == ["news-1", "fr-2", "fr-4"]     # INFO routine notice excluded


def test_merge_creates_storyline_and_appends_events():
    chronicle = {}
    assigns = [{"key": "ahrq-terminations", "title": "AHRQ grant terminations",
                "indexes": [0, 1]}]
    changed = sd._merge_chronicle(chronicle, assigns, ITEMS)
    assert changed == ["ahrq-terminations"]
    story = chronicle["ahrq-terminations"]
    assert story["title"] == "AHRQ grant terminations"
    assert [e["id"] for e in story["events"]] == ["news-1", "fr-2"]


def test_merge_skips_already_recorded_events():
    chronicle = {"ahrq-terminations": {"title": "AHRQ grant terminations",
                 "summary": "old", "events": [{"id": "news-1", "date": "2026-07-17"}]}}
    assigns = [{"key": "ahrq-terminations", "title": "AHRQ grant terminations",
                "indexes": [0]}]
    changed = sd._merge_chronicle(chronicle, assigns, ITEMS)
    assert changed == []                          # nothing new -> no change
    assert len(chronicle["ahrq-terminations"]["events"]) == 1


def test_chronicle_page_renders_sections_and_chronology():
    chronicle = {"ahrq-terminations": {
        "title": "AHRQ grant terminations",
        "summary": "AHRQ has terminated dozens of grants; appeals pending.",
        "events": [
            {"id": "b", "date": "2026-07-21", "title": "FR termination notice",
             "url": "https://federalregister.gov/y", "source": "Federal Register"},
            {"id": "a", "date": "2026-07-17", "title": "Press: AHRQ ends grants",
             "url": "https://insidehighered.com/x", "source": "News"},
        ]}}
    html_out = emailer.build_chronicle(chronicle)
    assert "AHRQ grant terminations" in html_out
    assert "appeals pending" in html_out
    # chronological order: earlier event appears before later one
    assert html_out.index("2026-07-17") < html_out.index("2026-07-21")
    assert "insidehighered.com" in html_out


def test_chronicle_page_empty_state():
    assert "No storylines recorded yet" in emailer.build_chronicle({})


def test_archive_index_links_chronicle():
    assert "chronicle.html" in emailer.build_archive_index(["2026-07-22"])
