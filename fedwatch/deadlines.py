"""Extract comment/response deadlines from federal notice text.

Looks for dates near deadline language ("responses due", "comment period
closes", "no later than", ...) in the title + summary.
"""

import re
from datetime import datetime

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}

# "August 3, 2026" / "August 3 2026"
_DATE_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+(\d{1,2})(?:,)?\s+(\d{4})\b", re.IGNORECASE)
# "2026-08-03" / "08/03/2026"
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_US_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_DEADLINE_CUES = [
    "due", "deadline", "close", "closes", "closing", "no later than",
    "on or before", "received by", "submitted by", "submit by", "respond",
    "responses", "comment period", "expires", "expiration",
]

_CONTEXT = 80  # chars around a date to look for deadline language


def _candidates(text: str):
    for m in _DATE_RE.finditer(text):
        month, day, year = m.groups()
        try:
            yield datetime(int(year), MONTHS[month.lower()], int(day)), m.start(), m.end()
        except ValueError:
            continue
    for m in _ISO_RE.finditer(text):
        y, mo, d = m.groups()
        try:
            yield datetime(int(y), int(mo), int(d)), m.start(), m.end()
        except ValueError:
            continue
    for m in _US_RE.finditer(text):
        mo, d, y = m.groups()
        try:
            yield datetime(int(y), int(mo), int(d)), m.start(), m.end()
        except ValueError:
            continue


def extract_deadline(item: dict) -> str | None:
    """Return the earliest future deadline (YYYY-MM-DD) found near deadline
    language, or None."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    now = datetime.now()
    found = []
    for dt, start, end in _candidates(text):
        if dt < now:
            continue
        window = text[max(0, start - _CONTEXT):min(len(text), end + _CONTEXT)]
        if any(cue in window for cue in _DEADLINE_CUES):
            found.append(dt)
    return min(found).strftime("%Y-%m-%d") if found else None


def days_until(date_str: str) -> int:
    return (datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.now().date()).days


def with_deadlines(items: list) -> list:
    """Items that carry a future deadline, each annotated with `deadline` and
    `days_left`, sorted soonest first."""
    out = []
    for it in items:
        deadline = extract_deadline(it)
        if deadline:
            annotated = dict(it)
            annotated["deadline"] = deadline
            annotated["days_left"] = days_until(deadline)
            out.append(annotated)
    return sorted(out, key=lambda i: i["deadline"])
