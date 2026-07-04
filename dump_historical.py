"""One-off: dump the NIH-focused candidate feed for a historical date window,
as the daily digest would have seen it on a given day.

Env: FR_GTE / FR_LTE (YYYY-MM-DD) bound the Federal Register publication date.
"""

import json
import os
import re
from datetime import datetime

import requests

from fedwatch import sources
from fedwatch.classify import DEFAULT_WATCHLIST, Classifier, sort_by_priority
from fedwatch.relevance import split_vetoed

GTE = os.environ["FR_GTE"]
LTE = os.environ["FR_LTE"]


def fr_window(terms, agency_slugs=None):
    params = {
        "conditions[publication_date][gte]": GTE,
        "conditions[publication_date][lte]": LTE,
        "per_page": 80, "order": "newest",
        "fields[]": ["title", "abstract", "html_url", "publication_date",
                     "agencies", "type", "document_number"],
    }
    if terms:
        params["conditions[term]"] = terms
    if agency_slugs:
        params["conditions[agencies][]"] = agency_slugs
    r = requests.get("https://www.federalregister.gov/api/v1/documents.json",
                     params=params, headers=sources.FETCH_HEADERS, timeout=30)
    r.raise_for_status()
    out = []
    for d in r.json().get("results", []):
        ags = d.get("agencies") or []
        out.append({
            "id": f"fr-{d.get('document_number')}", "source": "Federal Register",
            "agency": ags[0].get("name", "Unknown") if ags else "Unknown",
            "title": d.get("title", ""), "summary": (d.get("abstract") or "")[:350],
            "url": d.get("html_url", ""),
            "date": (d.get("publication_date") or "")[:10],
            "type": d.get("type", "Document"),
        })
    return out


items = []
items += fr_window(sources.FEDERAL_REGISTER_TERMS)
items += fr_window(None, sources.KEY_AGENCY_SLUGS)
# NIH funding opportunities in the window (Grants.gov close/open not date-filterable
# here; rely on FR + the standing sources for the example).
seen = set()
uniq = []
for it in items:
    if it["id"] not in seen:
        seen.add(it["id"]); uniq.append(it)

kept, _ = split_vetoed(uniq)
classified = Classifier(watchlist=DEFAULT_WATCHLIST).classify_all(kept)


def nih_focus(i):
    a = (i.get("agency") or "").lower()
    t = f"{i.get('title','')} {i.get('summary','')}".lower()
    return ("institutes of health" in a or "health and human services" in a
            or "management and budget" in a or "executive office" in a
            or "nih" in t or i.get("source") == "OMB Memoranda")


focused = sort_by_priority([i for i in classified if nih_focus(i)])
print(f"###HIST_START### window={GTE}..{LTE} candidates={len(uniq)} nih_focused={len(focused)}")
for i in focused:
    print("HIST " + json.dumps(i, ensure_ascii=False))
print("###HIST_END###")
