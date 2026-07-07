"""Outbound notifications: Microsoft Teams (incoming webhook) and SMTP email.

Teams setup: in your channel, ... menu -> Connectors / Workflows -> "Incoming
Webhook" -> copy the URL. Anyone with the URL can post to the channel, so
treat it as a secret.
"""

import smtplib
from email.message import EmailMessage

import requests

from .emailer import EMORY_BLUE, build_html, build_plain_text

TIMEOUT = 15


def _post_card(webhook_url: str, title: str, text: str, app_url: str = "") -> None:
    """Post an Adaptive Card to a Teams channel/chat via a Workflows webhook.

    Teams retired the classic Office 365 "Incoming Webhook" connector (which
    rendered legacy MessageCards) in favor of Workflows (Power Automate). The
    Workflows webhook expects a message envelope wrapping an Adaptive Card, so
    that is what we send here.
    """
    # Adaptive Card TextBlocks render a limited markdown subset (bold, italics,
    # links, bullet lists) but not '#' headers - strip leading hashes so they
    # don't show as literal "##".
    import re
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    body = [
        {"type": "TextBlock", "text": title, "weight": "Bolder",
         "size": "Large", "color": "Accent", "wrap": True},
        {"type": "TextBlock", "text": text, "wrap": True},
    ]
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }
    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": card,
        }],
    }
    resp = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()


def send_teams(webhook_url: str, items: list,
               title: str = "🔴 Critical federal research updates",
               app_url: str = "") -> None:
    """Post an alert card to a Teams channel via an incoming webhook."""
    if not webhook_url:
        raise ValueError("No Teams webhook URL configured")
    if not items:
        return
    lines = []
    for it in items:
        link = it.get("url") or ""
        name = it.get("title", "")
        entry = f"**[{it.get('level', '')}]** [{name}]({link})" if link else f"**[{it.get('level', '')}]** {name}"
        lines.append(f"- {entry}  \n  {it.get('agency', '')} · {it.get('date', '')}")
    _post_card(webhook_url, title, "\n".join(lines), app_url)


def send_teams_summary(webhook_url: str, summary_md: str,
                       title: str = "Federal Research Update - Executive Summary",
                       app_url: str = "") -> None:
    """Post a generated summary (markdown) to a Teams channel."""
    if not webhook_url:
        raise ValueError("No Teams webhook URL configured")
    if not summary_md.strip():
        raise ValueError("Summary is empty")
    _post_card(webhook_url, title, summary_md[:25000], app_url)


def send_slack(webhook_url: str, summary_md: str,
               title: str = "NIH RePORTER Weekly Report",
               link_url: str = "") -> None:
    """Post a generated summary to a Slack channel via an incoming webhook.

    When link_url is set, a clickable "View full digest" button/link is
    appended so recipients can open the styled HTML page.
    """
    if not webhook_url:
        raise ValueError("No Slack webhook URL configured")
    if not summary_md.strip():
        raise ValueError("Summary is empty")
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": title[:150], "emoji": True}},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": summary_md[:2900]}},
    ]
    if link_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "📄 View full digest", "emoji": True},
                "url": link_url,
            }],
        })
    resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=TIMEOUT)
    resp.raise_for_status()


def send_email(smtp_host: str, smtp_port: int, username: str, password: str,
               sender: str, recipients: str, items: list, summary_md: str = "",
               title: str = "🔴 Critical federal research updates") -> None:
    """Send the sanitized digest over SMTP (STARTTLS)."""
    if not items:
        return
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender
    msg["To"] = recipients
    msg.set_content(build_plain_text(items, summary_md, title))
    msg.add_alternative(build_html(items, summary_md, title), subtype="html")

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        if username:
            server.login(username, password)
        server.send_message(msg)
