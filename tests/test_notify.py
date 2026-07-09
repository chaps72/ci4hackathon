"""Tests for outbound notification payloads: Slack mrkdwn conversion and
block layout, and the Teams Adaptive Card envelope."""

import fedwatch.notify as notify


class _Resp:
    def raise_for_status(self):
        pass


def _capture_post(store):
    def fake_post(url, json=None, timeout=None):
        store.append({"url": url, "payload": json})
        return _Resp()
    return fake_post


# --------------------------------------------------------------------------
# Markdown -> Slack mrkdwn

def test_mrkdwn_converts_bold():
    assert notify._to_mrkdwn("**Bottom line:** all clear") == "*Bottom line:* all clear"


def test_mrkdwn_converts_headers():
    assert notify._to_mrkdwn("## Executive Summary") == "*Executive Summary*"


def test_mrkdwn_converts_links():
    assert notify._to_mrkdwn("see [the rule](https://x.gov/doc)") == "see <https://x.gov/doc|the rule>"


def test_mrkdwn_leaves_plain_text_alone():
    text = "Plain text with - bullets\n- one\n- two"
    assert notify._to_mrkdwn(text) == text


# --------------------------------------------------------------------------
# Slack payload

def test_send_slack_converts_markdown_and_has_no_button(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.requests, "post", _capture_post(calls))
    notify.send_slack("http://hook", "## Summary\n**Bottom line:** ok",
                      title="FedWatch Daily")
    blocks = calls[0]["payload"]["blocks"]
    types = [b["type"] for b in blocks]
    assert types == ["header", "section"]          # no actions/button block
    assert blocks[1]["text"]["text"] == "*Summary*\n*Bottom line:* ok"


def test_send_slack_appends_extra_section_with_divider(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.requests, "post", _capture_post(calls))
    notify.send_slack("http://hook", "body", title="T",
                      extra_md="🏛️ Government affairs\nquiet week")
    types = [b["type"] for b in calls[0]["payload"]["blocks"]]
    assert types == ["header", "section", "divider", "section"]


def test_send_slack_rejects_empty_summary():
    import pytest
    with pytest.raises(ValueError):
        notify.send_slack("http://hook", "   ")


# --------------------------------------------------------------------------
# Teams Adaptive Card payload (modern Workflows webhook format)

def test_teams_card_is_adaptive_card_envelope(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.requests, "post", _capture_post(calls))
    notify.send_teams_summary("http://hook", "## Summary\nbody", title="T")
    payload = calls[0]["payload"]
    assert payload["type"] == "message"
    att = payload["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = att["content"]
    assert card["type"] == "AdaptiveCard"
    # '#' headers are stripped (Adaptive Card TextBlock doesn't render them)
    assert "##" not in card["body"][1]["text"]


def test_teams_summary_appends_extra_md(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.requests, "post", _capture_post(calls))
    notify.send_teams_summary("http://hook", "body", title="T",
                              extra_md="⏰ Deadlines\n- item")
    card = calls[0]["payload"]["attachments"][0]["content"]
    assert "⏰ Deadlines" in card["body"][1]["text"]
