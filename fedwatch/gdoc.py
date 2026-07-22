"""Sync the historical record into a Google Doc.

Uses a Google Cloud service account (Docs API) to rewrite one shared Doc in
place, so the reader always opens the same document and sees the current
chronicle. Configured via:

    GOOGLE_SERVICE_ACCOUNT_JSON  - full JSON key of the service account
    CHRONICLE_GDOC_ID            - the Doc id from its URL (/document/d/<ID>/)

The Doc must be shared with the service account's email as Editor.
Everything here fails soft: without configuration, or on any API error,
sync_chronicle_doc simply returns False.
"""

import json
import os

import requests

TIMEOUT = 30
_DOCS_API = "https://docs.googleapis.com/v1/documents"


def chronicle_text(chronicle: dict, generated: str = "") -> str:
    """Plain-text rendering of the chronicle for the Google Doc: one section
    per storyline (most recently active first) with its state-of-play summary
    and dated chronology."""
    def last_date(s):
        return max((ev.get("date") or "" for ev in s.get("events", [])), default="")
    lines = ["FEDWATCH — HISTORICAL RECORD",
             "Chronology of federal research-policy sagas · Office of the SVPR"]
    if generated:
        lines.append(f"Updated {generated}")
    lines.append("")
    for key, s in sorted(chronicle.items(), key=lambda kv: last_date(kv[1]), reverse=True):
        title = s.get("title", key)
        lines.append(title.upper())
        lines.append("─" * min(len(title), 60))
        if s.get("summary"):
            lines.append(s["summary"])
        lines.append("")
        for ev in sorted(s.get("events", []), key=lambda e: e.get("date") or ""):
            lines.append(f"  {ev.get('date', '????-??-??')}  {ev.get('title', '')}"
                         f"  [{ev.get('source', '')}]")
            if ev.get("url"):
                lines.append(f"      {ev['url']}")
        lines.append("")
    if not chronicle:
        lines.append("No storylines recorded yet.")
    return "\n".join(lines)


def _access_token(sa_info: dict) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/documents"])
    creds.refresh(Request())
    return creds.token


def sync_chronicle_doc(text: str) -> bool:
    """Rewrite the configured Google Doc with `text`. Returns True on success,
    False when unconfigured or on any failure (logged, never raised)."""
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    doc_id = os.environ.get("CHRONICLE_GDOC_ID", "")
    if not sa_json or not doc_id:
        return False
    try:
        token = _access_token(json.loads(sa_json))
        headers = {"Authorization": f"Bearer {token}"}
        doc = requests.get(f"{_DOCS_API}/{doc_id}", headers=headers,
                           timeout=TIMEOUT)
        doc.raise_for_status()
        end = doc.json()["body"]["content"][-1].get("endIndex", 1)
        reqs = []
        if end > 2:  # Docs requires leaving the final newline in place
            reqs.append({"deleteContentRange":
                         {"range": {"startIndex": 1, "endIndex": end - 1}}})
        reqs.append({"insertText": {"location": {"index": 1}, "text": text}})
        resp = requests.post(f"{_DOCS_API}/{doc_id}:batchUpdate",
                             headers=headers, json={"requests": reqs},
                             timeout=TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - the Doc sync must never block a run
        print(f"Google Doc sync failed ({exc}); continuing.")
        return False
