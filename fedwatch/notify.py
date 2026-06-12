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


def send_teams(webhook_url: str, items: list,
               title: str = "🔴 Critical federal research updates") -> None:
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
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": EMORY_BLUE.lstrip("#"),
        "summary": title,
        "title": title,
        "sections": [{"text": "\n".join(lines)}],
    }
    resp = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()


def send_teams_summary(webhook_url: str, summary_md: str,
                       title: str = "Federal Research Update - Executive Summary") -> None:
    """Post a generated summary (markdown) to a Teams channel."""
    if not webhook_url:
        raise ValueError("No Teams webhook URL configured")
    if not summary_md.strip():
        raise ValueError("Summary is empty")
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": EMORY_BLUE.lstrip("#"),
        "summary": title,
        "title": title,
        "sections": [{"text": summary_md[:25000]}],
    }
    resp = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
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
