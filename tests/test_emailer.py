"""Tests for the HTML digest rendering: badges, impact block, and escaping."""

import fedwatch.emailer as emailer


def _item(**over):
    base = {"level": "HIGH", "title": "Test item", "agency": "NIH",
            "date": "2026-07-08", "source": "Federal Register",
            "summary": "sum", "url": "https://fr.gov/doc"}
    base.update(over)
    return base


def test_deadline_and_comment_badges_render():
    html = emailer.build_html([_item(comment_due="2026-09-08",
                                     comment_opportunity=True,
                                     comment_url="https://regulations.gov/c/1")],
                              "s", "T")
    assert "Comment due 2026-09-08" in html
    assert "Comment opportunity" in html
    assert "https://regulations.gov/c/1" in html


def test_effective_badge_renders_without_comment_due():
    html = emailer.build_html([_item(effective_on="2026-08-07")], "s", "T")
    assert "Effective 2026-08-07" in html


def test_update_note_badge_renders():
    html = emailer.build_html([_item(update_note="Finalizes an earlier proposed rule.")],
                              "s", "T")
    assert "Finalizes an earlier proposed rule." in html


def test_impact_block_has_severity_and_svpr_but_no_owner():
    html = emailer.build_html([_item(impact="Impact text", exposure="high",
                                     svpr_impact="SVPR line", owner="OSP",
                                     action="Do a thing")], "s", "T")
    assert "HIGH severity" in html
    assert "SVPR office:" in html
    assert "Owner:" not in html
    assert "Action:" not in html


def test_feed_content_is_escaped():
    html = emailer.build_html([_item(title='<script>alert(1)</script>')], "s", "T")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_unsafe_urls_are_dropped():
    html = emailer.build_html([_item(url="javascript:alert(1)")], "s", "T")
    assert "javascript:" not in html
