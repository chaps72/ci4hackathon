"""Fetchers for federal research update sources.

All fetchers return a list of dicts with a common shape:
    id, source, agency, title, summary, url, date (YYYY-MM-DD), type

Every fetcher fails soft (returns [] and records the error) so one broken
feed never takes down the dashboard. `fetch_all` falls back to bundled
sample data when nothing could be fetched (e.g., no network).
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from .sample_data import SAMPLE_ITEMS

TIMEOUT = 15
USER_AGENT = "FedWatch-internal/0.1 (research policy awareness dashboard)"

# Search terms used against the Federal Register full-text API.
FEDERAL_REGISTER_TERMS = "research grants OR research funding OR federally funded research"

NIH_GUIDE_RSS = "https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml"
NSF_NEWS_RSS = "https://www.nsf.gov/rss/rss_www_news.xml"


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").replace("&nbsp;", " ").strip()


def _norm_date(value: str) -> str:
    """Best-effort normalization of assorted feed date formats to YYYY-MM-DD."""
    if not value:
        return ""
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:31], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value[:10]


def fetch_federal_register(days_back: int = 14, errors: list | None = None) -> list:
    """Federal Register public API (no key required)."""
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://www.federalregister.gov/api/v1/documents.json",
            params={
                "conditions[term]": FEDERAL_REGISTER_TERMS,
                "conditions[publication_date][gte]": since,
                "per_page": 40,
                "order": "newest",
                "fields[]": ["title", "abstract", "html_url", "publication_date",
                             "agencies", "type", "document_number"],
            },
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = []
        for doc in resp.json().get("results", []):
            agencies = doc.get("agencies") or []
            agency = agencies[0].get("name", "Unknown") if agencies else "Unknown"
            items.append({
                "id": f"fr-{doc.get('document_number')}",
                "source": "Federal Register",
                "agency": agency,
                "title": doc.get("title", ""),
                "summary": doc.get("abstract") or "",
                "url": doc.get("html_url", ""),
                "date": _norm_date(doc.get("publication_date", "")),
                "type": doc.get("type", "Document"),
            })
        return items
    except Exception as e:  # noqa: BLE001 - fail soft by design
        if errors is not None:
            errors.append(f"Federal Register: {e}")
        return []


def fetch_grants_gov(keyword: str = "research", errors: list | None = None) -> list:
    """Grants.gov Search2 API (public, no key required)."""
    try:
        resp = requests.post(
            "https://api.grants.gov/v1/api/search2",
            json={"keyword": keyword, "oppStatuses": "posted", "rows": 30,
                  "sortBy": "openDate|desc"},
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("data", {}).get("oppHits", []) or []
        items = []
        for opp in hits:
            opp_id = opp.get("id") or opp.get("number", "")
            close = opp.get("closeDate") or ""
            summary = f"Funding opportunity {opp.get('number', '')} from {opp.get('agencyName', 'unknown agency')}."
            if close:
                summary += f" Closing date: {close}."
            items.append({
                "id": f"gg-{opp_id}",
                "source": "Grants.gov",
                "agency": opp.get("agencyName", "Unknown"),
                "title": opp.get("title", ""),
                "summary": summary,
                "url": f"https://www.grants.gov/search-results-detail/{opp_id}",
                "date": _norm_date(opp.get("openDate", "")),
                "type": "Funding Opportunity",
            })
        return items
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"Grants.gov: {e}")
        return []


def _fetch_rss(url: str, source: str, agency: str, errors: list | None = None) -> list:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for n, entry in enumerate(root.iter("item")):
            link = (entry.findtext("link") or "").strip()
            items.append({
                "id": f"{source.lower().replace(' ', '')}-{link or n}",
                "source": source,
                "agency": agency,
                "title": (entry.findtext("title") or "").strip(),
                "summary": _strip_html(entry.findtext("description") or "")[:800],
                "url": link,
                "date": _norm_date(entry.findtext("pubDate") or ""),
                "type": "Feed Item",
            })
        return items[:30]
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"{source}: {e}")
        return []


def fetch_nih_guide(errors: list | None = None) -> list:
    return _fetch_rss(NIH_GUIDE_RSS, "NIH Guide", "National Institutes of Health", errors)


def fetch_nsf_news(errors: list | None = None) -> list:
    return _fetch_rss(NSF_NEWS_RSS, "NSF News", "National Science Foundation", errors)


def fetch_all(days_back: int = 14, grants_keyword: str = "research"):
    """Fetch every source. Returns (items, errors, used_sample_data)."""
    errors: list[str] = []
    items = []
    items += fetch_federal_register(days_back=days_back, errors=errors)
    items += fetch_grants_gov(keyword=grants_keyword, errors=errors)
    items += fetch_nih_guide(errors=errors)
    items += fetch_nsf_news(errors=errors)

    # Dedupe by id, newest first
    seen, deduped = set(), []
    for item in sorted(items, key=lambda i: i.get("date", ""), reverse=True):
        if item["id"] not in seen:
            seen.add(item["id"])
            deduped.append(item)

    if not deduped:
        return list(SAMPLE_ITEMS), errors, True
    return deduped, errors, False
