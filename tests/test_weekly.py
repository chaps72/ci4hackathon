"""Tests for the weekly Word-summary generator."""

import json

import weekly_summary as ws

LOG = [
    {"date": "2026-07-22", "summary": "Wed bottom line.",
     "items": [{"title": "FR notice", "url": "https://fr.gov/a",
                "level": "HIGH", "agency": "NIH"}],
     "press": [{"title": "AHRQ story", "url": "https://ihe.com/x", "agency": "IHE"}]},
    {"date": "2026-07-10", "summary": "outside window", "items": [], "press": []},
]
CHRONICLE = {
    "ahrq": {"title": "AHRQ grant terminations", "summary": "Ongoing saga.",
             "events": [{"id": "e1", "date": "2026-07-22", "title": "x"}]},
    "old": {"title": "Old saga", "summary": "done",
            "events": [{"id": "e2", "date": "2026-06-01", "title": "y"}]},
}


def test_week_entries_filters_window_and_sorts():
    days = ws.week_entries(LOG, "2026-07-20", "2026-07-26")
    assert [d["date"] for d in days] == ["2026-07-22"]


def test_active_storylines_only_with_events_in_window():
    active = ws.active_storylines(CHRONICLE, "2026-07-20", "2026-07-26")
    assert [s["title"] for s in active] == ["AHRQ grant terminations"]


def test_template_narrative_counts():
    text = ws._template_narrative([LOG[0]], "2026-07-20", "2026-07-26")
    assert "1 federal actions" in text and "1 press" in text


def test_build_docx_produces_readable_document(tmp_path):
    out = tmp_path / "weekly.docx"
    ws.build_docx(str(out), "2026-07-20", "2026-07-26",
                  "Bottom line.\nKey developments follow.",
                  [LOG[0]], [CHRONICLE["ahrq"]])
    from docx import Document
    doc = Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "FedWatch Weekly Summary" in text
    assert "Bottom line." in text
    assert "AHRQ grant terminations" in text
    assert "[HIGH]" in text and "[press]" in text
