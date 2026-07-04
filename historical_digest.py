"""Full historical digest run for a fixed date window: fetch -> NIH focus ->
AI relevance -> Emory impact -> styled HTML page. Writes the page into the
repo (docs/digests/) and prints the summary to the log.

Env: FR_GTE / FR_LTE (YYYY-MM-DD).
"""

import os
import pathlib
from datetime import datetime

import requests

from fedwatch import emailer, sources, summarize
from fedwatch.classify import DEFAULT_WATCHLIST, Classifier, sort_by_priority
from fedwatch.relevance import split_vetoed

GTE, LTE = os.environ["FR_GTE"], os.environ["FR_LTE"]


def fr(terms, agency_slugs=None):
    params = {"conditions[publication_date][gte]": GTE,
              "conditions[publication_date][lte]": LTE,
              "per_page": 80, "order": "newest",
              "fields[]": ["title", "abstract", "html_url", "publication_date",
                           "agencies", "type", "document_number"]}
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
        out.append({"id": f"fr-{d.get('document_number')}", "source": "Federal Register",
                    "agency": ags[0].get("name", "Unknown") if ags else "Unknown",
                    "title": d.get("title", ""), "summary": (d.get("abstract") or "")[:350],
                    "url": d.get("html_url", ""),
                    "date": (d.get("publication_date") or "")[:10],
                    "type": d.get("type", "Document")})
    return out


items = fr(sources.FEDERAL_REGISTER_TERMS) + fr(None, sources.KEY_AGENCY_SLUGS)
# OMB memos dated within the window (dates derived from URL by the fetcher)
items += [m for m in sources.fetch_omb_memoranda() if GTE <= (m.get("date") or "z") <= LTE]

seen, uniq = set(), []
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


focused = [i for i in classified if nih_focus(i)]
if summarize.claude_available():
    focused = [i for i in summarize.ai_classify(focused) if i.get("relevant", True)]
    focused = summarize.analyze_emory_impact(focused)
focused = sort_by_priority(focused)

summary, engine = summarize.generate_summary(focused, "Executive summary")
title = f"FedWatch Daily - NIH & Research Policy · {LTE} (example)"
html = emailer.build_html(focused, summary, title)

path = pathlib.Path(f"docs/digests/example-{LTE}.html")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(html, encoding="utf-8")

print(f"### window {GTE}..{LTE} | candidates={len(uniq)} | kept={len(focused)} | engine={engine}")
print("### SUMMARY ###")
print(summary)
for i in focused:
    print(f"\n[{i['level']}] {i.get('title','')[:80]}  ({i.get('agency','')})")
    if i.get("impact"):
        print(f"  Emory impact [{i.get('exposure','?')}]: {i['impact']}")
        print(f"  Owner: {i.get('owner','?')} | Action: {i.get('action','?')}")
print(f"### page written: {path}")
