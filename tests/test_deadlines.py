"""Tests for deadline extraction: structured Federal Register fields are
authoritative, text regex is the fallback."""

from datetime import datetime, timedelta

from fedwatch import deadlines


def _future(days=30, fmt="%B %d, %Y"):
    return (datetime.now() + timedelta(days=days)).strftime(fmt)


def test_structured_field_wins_over_text():
    item = {"comment_due": "2026-09-08",
            "title": "Notice", "summary": f"Comments due {_future(60)}."}
    assert deadlines.extract_deadline(item) == "2026-09-08"


def test_regex_fallback_finds_deadline_near_cue():
    item = {"title": "RFI", "summary": f"Responses must be received by {_future()}."}
    got = deadlines.extract_deadline(item)
    assert got == (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")


def test_date_without_deadline_language_is_ignored():
    item = {"title": "Notice", "summary": f"A meeting was held on {_future()}."}
    assert deadlines.extract_deadline(item) is None


def test_past_dates_are_ignored_by_regex():
    past = (datetime.now() - timedelta(days=30)).strftime("%B %d, %Y")
    item = {"title": "Notice", "summary": f"Comments were due {past}."}
    assert deadlines.extract_deadline(item) is None


def test_with_deadlines_annotates_and_sorts_and_skips_past():
    soon, later = _future(5), _future(50)
    past_structured = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    items = [
        {"title": "B", "summary": f"Submit by {later}."},
        {"title": "A", "summary": f"Submit by {soon}."},
        {"title": "expired", "comment_due": past_structured},
        {"title": "no deadline", "summary": "nothing here"},
    ]
    out = deadlines.with_deadlines(items)
    assert [i["title"] for i in out] == ["A", "B"]
    assert out[0]["days_left"] >= 0
