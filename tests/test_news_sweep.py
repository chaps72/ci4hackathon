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
