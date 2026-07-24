"""Tests for the daily digest pipeline's fragile logic: scheduling guards,
dedupe/force interaction, update flagging, deadline sections, and state
pruning/migration."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import send_digest as sd

ET = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------
# Scheduled-run guards

def test_guards_skip_weekend(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    saturday = datetime(2026, 7, 11, 17, 30, tzinfo=ET)
    assert sd._scheduled_run_guards(saturday) == "weekend"


def test_guards_skip_holiday(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    # July 4, 2026 falls on a Saturday; observed Friday July 3.
    observed = datetime(2026, 7, 3, 17, 30, tzinfo=ET)
    assert "holiday" in sd._scheduled_run_guards(observed)


def test_guards_allow_weekday_regardless_of_hour(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    early = datetime(2026, 7, 8, 16, 30, tzinfo=ET)   # Wednesday, pre-5pm armer
    late = datetime(2026, 7, 8, 18, 45, tzinfo=ET)    # delayed backup cron
    assert sd._scheduled_run_guards(early) == ""      # runs, then holds for 5pm
    assert sd._scheduled_run_guards(late) == ""


def test_hold_until_5pm_waits_before_and_not_after():
    early = datetime(2026, 7, 8, 16, 30, 0, tzinfo=ET)
    exactly = datetime(2026, 7, 8, 17, 0, 0, tzinfo=ET)
    late = datetime(2026, 7, 8, 18, 45, 0, tzinfo=ET)
    assert sd._seconds_until_5pm_et(early) == 30 * 60
    assert sd._seconds_until_5pm_et(exactly) == 0
    assert sd._seconds_until_5pm_et(late) == 0


def test_guards_bypass_for_manual_runs(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert sd._scheduled_run_guards(datetime(2026, 7, 11, 3, 0, tzinfo=ET)) == ""


# --------------------------------------------------------------------------
# Digest scope: NIH first, plus NSF and research-relevant DOD

def _scoped(monkeypatch, item):
    monkeypatch.setenv("FEDWATCH_FOCUS", "nih")
    return sd._nih_focused([item])


def test_scope_keeps_nsf(monkeypatch):
    item = {"agency": "National Science Foundation", "title": "IPA policy update",
            "summary": "changes to rotator program"}
    assert _scoped(monkeypatch, item) == [item]


def test_scope_keeps_dod_with_research_signal(monkeypatch):
    item = {"agency": "Defense Department", "title": "Basic research funding at universities",
            "summary": "changes to 6.1 basic research programs"}
    assert _scoped(monkeypatch, item) == [item]


def test_scope_drops_dod_without_research_signal(monkeypatch):
    item = {"agency": "Defense Department", "title": "TRICARE co-pay adjustment",
            "summary": "military health plan billing"}
    assert _scoped(monkeypatch, item) == []


def test_scope_keeps_nih(monkeypatch):
    item = {"agency": "National Institutes of Health", "title": "Notice", "summary": ""}
    assert _scoped(monkeypatch, item) == [item]


def test_scope_all_disables_filter(monkeypatch):
    monkeypatch.setenv("FEDWATCH_FOCUS", "all")
    item = {"agency": "Department of the Interior", "title": "x", "summary": "y"}
    assert sd._nih_focused([item]) == [item]


# --------------------------------------------------------------------------
# Update flagging (new items only, but mark follow-ups)

HISTORY = [
    {"id": "fr-A", "date": "2026-06-20", "docket": "NIH-2026-0034",
     "type": "Proposed Rule", "title": "Proposed cap on grants"},
    {"id": "fr-B", "date": "2026-06-25", "docket": "HHS-2026-0100",
     "type": "Notice", "title": "Some notice"},
]


def test_mark_updates_flags_finalized_rule():
    items = [{"id": "fr-C", "docket": "NIH-2026-0034", "type": "Rule",
              "title": "Final rule: cap on grants"}]
    sd._mark_updates(items, HISTORY)
    assert "Finalizes an earlier proposed rule" in items[0]["update_note"]
    assert "NIH-2026-0034" in items[0]["update_note"]


def test_mark_updates_flags_same_docket_followup():
    items = [{"id": "fr-D", "docket": "HHS-2026-0100", "type": "Notice",
              "title": "Comment period extended"}]
    sd._mark_updates(items, HISTORY)
    assert "Update to earlier coverage" in items[0]["update_note"]


def test_mark_updates_flags_corrections():
    items = [{"id": "fr-E", "type": "Correction", "title": "Correction: notice"}]
    sd._mark_updates(items, HISTORY)
    assert "Correction" in items[0]["update_note"]


def test_mark_updates_leaves_new_items_unflagged():
    items = [{"id": "fr-F", "docket": "NSF-2026-1", "type": "Notice",
              "title": "Brand new item"}]
    sd._mark_updates(items, HISTORY)
    assert "update_note" not in items[0]


def test_updates_section_empty_without_flags():
    assert sd._updates_section([{"id": "x", "title": "t"}]) == ""


# --------------------------------------------------------------------------
# Deadlines section

def test_deadlines_section_uses_structured_fields():
    items = [{"title": "RFI on caps", "comment_due": "2026-09-08",
              "comment_opportunity": True, "comment_url": "http://reg/x"}]
    out = sd._deadlines_section(items)
    assert "comment due 2026-09-08" in out
    assert "http://reg/x" in out


def test_deadlines_section_falls_back_to_text_extraction():
    future = (datetime.now() + timedelta(days=30)).strftime("%B %d, %Y")
    items = [{"title": "NIH notice", "summary": f"Responses are due {future}."}]
    out = sd._deadlines_section(items)
    assert "⏰ due" in out


def test_deadlines_section_empty_when_no_dates():
    assert sd._deadlines_section([{"title": "plain notice", "summary": "text"}]) == ""


# --------------------------------------------------------------------------
# State: seen-cache migration + pruning, history pruning

def test_load_seen_migrates_legacy_list(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text(json.dumps(["fr-1", "sent:2026-07-01"]))
    seen = sd._load_seen(str(p))
    today = datetime.now().strftime("%Y-%m-%d")
    assert seen == {"fr-1": today, "sent:2026-07-01": today}


def test_load_seen_missing_file(tmp_path):
    assert sd._load_seen(str(tmp_path / "nope.json")) == {}


def test_prune_seen_drops_old_and_undated():
    today = datetime.now().strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=sd.SEEN_RETENTION_DAYS + 5)).strftime("%Y-%m-%d")
    seen = {"new": today, "old": old, "undated": ""}
    assert sd._prune_seen(seen) == {"new": today}


def test_save_and_reload_seen_roundtrip(tmp_path):
    p = tmp_path / "seen.json"
    today = datetime.now().strftime("%Y-%m-%d")
    sd._save_seen(str(p), {"fr-1": today})
    assert sd._load_seen(str(p)) == {"fr-1": today}


def test_prune_history_keeps_recent_drops_old_and_undated():
    today = datetime.now().strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=sd.HISTORY_RETENTION_DAYS + 2)).strftime("%Y-%m-%d")
    history = [{"date": today}, {"date": old}, {"date": ""}]
    assert sd._prune_history(history) == [{"date": today}]


# --------------------------------------------------------------------------
# Compact Teams tail

def test_teams_sections_top_deadlines_and_press_only():
    official = [
        {"title": "RFI on grant caps with a very long descriptive federal register title",
         "comment_due": "2026-09-08"},
        {"title": "Effective rule", "effective_on": "2026-08-07"},
        {"title": "No dates here"},
    ]
    press = [{"title": "AHRQ ends dozens of grants", "agency": "Science",
              "url": "https://science.org/x"}]
    out = sd._teams_sections(official, press)
    assert "comment due 2026-09-08" in out
    assert "effective 2026-08-07" in out
    assert "[AHRQ ends dozens of grants](https://science.org/x)" in out
    assert "No dates here" not in out
    assert "Trend" not in out and "Government affairs" not in out


def test_teams_sections_empty_when_nothing_qualifies():
    assert sd._teams_sections([{"title": "plain"}], []) == ""


# --------------------------------------------------------------------------
# Criticality banner (original 'notification of level' promise)

def test_level_line_counts_by_level_and_press():
    official = [{"level": "CRITICAL"}, {"level": "HIGH"}, {"level": "HIGH"},
                {"level": "INFO"}]
    press = [{"title": "story"}]
    line = sd._level_line(official, press)
    assert "1 critical" in line and "2 high" in line and "1 info" in line
    assert "📰 1 press" in line
    assert "moderate" not in line          # zero counts omitted


def test_level_line_empty_when_no_items():
    assert sd._level_line([], []) == ""
