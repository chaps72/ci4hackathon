"""Tests for the press news sweep: model-output normalization and how News
items flow through the relevance and scope filters."""

import json
from datetime import datetime, timedelta

from fedwatch import summarize
from fedwatch.relevance import filter_relevant
import send_digest as sd


def _entry(**over):
    base = {"title": "Administration ends dozens of grants studying patient care",
            "outlet": "Science", "date": datetime.now().strftime("%Y-%m-%d"),
            "url": "https://www.science.org/content/article/x",
            "summary": "AHRQ terminated dozens of health services research grants."}
    base.update(over)
    return base


def test_news_items_normalized_with_stable_id():
    raw = json.dumps([_entry()])
    items = summarize._news_sweep_items(raw, days_back=2)
    assert len(items) == 1
    it = items[0]
    assert it["type"] == "News" and it["source"] == "News"
    assert it["agency"] == "Science"
    assert it["id"].startswith("news-")
    # Same URL -> same id (dedupe across days)
    again = summarize._news_sweep_items(raw, days_back=2)[0]
    assert again["id"] == it["id"]


def test_news_items_drop_bad_urls_and_duplicates():
    raw = json.dumps([_entry(url="javascript:alert(1)"),
                      _entry(), _entry()])   # dup URL
    items = summarize._news_sweep_items(raw, days_back=2)
    assert len(items) == 1


def test_news_items_drop_stale_dates():
    old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    raw = json.dumps([_entry(date=old)])
    assert summarize._news_sweep_items(raw, days_back=2) == []


def test_news_items_survive_garbage_output():
    assert summarize._news_sweep_items("I could not find anything.", 2) == []
    assert summarize._news_sweep_items('{"not": "a list"}', 2) == []


def test_news_passes_relevance_filter():
    items = summarize._news_sweep_items(json.dumps([_entry()]), days_back=2)
    kept, dropped = filter_relevant(items)
    assert kept and not dropped


def test_news_passes_nih_focus_filter(monkeypatch):
    monkeypatch.setenv("FEDWATCH_FOCUS", "nih")
    item = {"type": "News", "source": "News", "agency": "Science",
            "title": "NSF slashes graduate fellowships", "summary": ""}
    assert sd._nih_focused([item]) == [item]


# --------------------------------------------------------------------------
# Separate press section (message + HTML)

import fedwatch.emailer as emailer

PRESS = {"type": "News", "source": "News", "agency": "Science",
         "title": "Administration ends dozens of grants", "date": "2026-07-19",
         "summary": "AHRQ terminated dozens of grants.", "level": "HIGH",
         "url": "https://www.science.org/content/article/x"}
OFFICIAL = {"type": "Notice", "source": "Federal Register", "agency": "NIH",
            "title": "Official notice", "level": "HIGH", "id": "fr-1"}


def test_split_press_separates_news_from_official():
    official, press = sd._split_press([PRESS, OFFICIAL])
    assert official == [OFFICIAL]
    assert press == [PRESS]


def test_press_section_lists_outlet_date_and_url():
    out = sd._press_section([PRESS])
    assert "From the research press" in out
    assert "Science, 2026-07-19" in out
    assert "https://www.science.org/content/article/x" in out


def test_press_section_empty_without_stories():
    assert sd._press_section([]) == ""


def test_html_renders_press_in_own_section():
    html_out = emailer.build_html([OFFICIAL], "s", "T", press_items=[PRESS])
    assert "From the research press" in html_out
    assert "press coverage" in html_out
    assert "science.org" in html_out


def test_html_no_press_section_when_empty():
    html_out = emailer.build_html([OFFICIAL], "s", "T")
    assert "From the research press" not in html_out
