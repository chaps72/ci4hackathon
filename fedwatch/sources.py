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
# Quoted phrases joined with | (OR): an unquoted query matches documents
# containing ANY single word ("funding" alone pulls in Medicare rules etc.).
FEDERAL_REGISTER_TERMS = (
    '"research funding" | "research grant" | "research grants" | '
    '"federally funded research" | "scientific research" | '
    '"research institutions" | "extramural research" | '
    '"research policy" | "research security" | "research misconduct" | '
    '"scientific integrity" | "research integrity"'
)

# NIH Guide has separate feeds: notices.xml carries policy/administrative
# notices (the government-affairs signal); fundingopps.xml carries NOFOs.
NIH_GUIDE_NOTICES_RSS = "https://grants.nih.gov/grants/guide/newsfeed/notices.xml"
NIH_GUIDE_FUNDING_RSS = "https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml"
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


def fetch_federal_register(days_back: int = 14, errors: list | None = None,
                           terms: str | None = None) -> list:
    """Federal Register public API (no key required)."""
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://www.federalregister.gov/api/v1/documents.json",
            params={
                "conditions[term]": terms or FEDERAL_REGISTER_TERMS,
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


def _fetch_rss(url: str, source: str, agency: str, errors: list | None = None,
               item_type: str = "Feed Item") -> list:
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
                "type": item_type,
            })
        return items
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"{source}: {e}")
        return []


def fetch_nih_notices(errors: list | None = None) -> list:
    return _fetch_rss(NIH_GUIDE_NOTICES_RSS, "NIH Guide", "National Institutes of Health",
                      errors, item_type="Policy Notice")


def fetch_nih_funding(errors: list | None = None) -> list:
    return _fetch_rss(NIH_GUIDE_FUNDING_RSS, "NIH Guide", "National Institutes of Health",
                      errors, item_type="Funding Opportunity")


def fetch_nsf_news(errors: list | None = None) -> list:
    return _fetch_rss(NSF_NEWS_RSS, "NSF News", "National Science Foundation", errors)


def fetch_watchlist_targeted(watchlist: list, errors: list | None = None,
                             days_back: int = 90) -> list:
    """Dedicated Federal Register search for the team's watchlist terms.

    Guarantees watched topics are found even when they fall outside the main
    query's phrasing or lookback window. Matches are flagged so downstream
    filters never drop them.
    """
    terms = " | ".join(f'"{w}"' for w in watchlist if w and w.strip())
    if not terms:
        return []
    items = fetch_federal_register(days_back=days_back, errors=errors, terms=terms)
    for it in items:
        it["watchlist_targeted"] = True
    return items


def fetch_all(days_back: int = 14, grants_keyword: str = "research",
              include_funding: bool = False, include_news: bool = False,
              watchlist: list | None = None):
    """Fetch every source. Returns (items, errors, used_sample_data).

    Default focus is research policy / government affairs: Federal Register
    documents and NIH policy notices. Funding-opportunity sources (Grants.gov,
    NIH NOFO feed) require include_funding; agency press releases (NSF News:
    podcasts, discovery stories, award announcements) require include_news.
    """
    errors: list[str] = []
    items = []
    items += fetch_federal_register(days_back=days_back, errors=errors)
    items += fetch_nih_notices(errors=errors)
    if include_news:
        items += fetch_nsf_news(errors=errors)
    if include_funding:
        items += fetch_grants_gov(keyword=grants_keyword, errors=errors)
        items += fetch_nih_funding(errors=errors)

    targeted = fetch_watchlist_targeted(watchlist or [], errors=errors)
    targeted_ids = {i["id"] for i in targeted}
    items += targeted

    # Dedupe by id, newest first; preserve the watchlist-targeted flag
    seen, deduped = set(), []
    for item in sorted(items, key=lambda i: i.get("date", ""), reverse=True):
        if item["id"] not in seen:
            seen.add(item["id"])
            if item["id"] in targeted_ids:
                item["watchlist_targeted"] = True
            deduped.append(item)

    def _mode_filter(seq: list) -> list:
        # Watchlist-targeted items are exempt from mode filtering.
        if not include_funding:
            seq = [i for i in seq if i.get("watchlist_targeted") or not _is_funding_item(i)]
        if not include_news:
            seq = [i for i in seq if i.get("watchlist_targeted") or i.get("source") != "NSF News"]
        return seq

    if not deduped:
        return _mode_filter(list(SAMPLE_ITEMS)), errors, True
    return _mode_filter(deduped), errors, False


# Funding-opportunity announcements also appear in policy feeds (NIH notices,
# Federal Register) - in policy mode, drop them by title as well as by type.
_FUNDING_TITLE_MARKERS = [
    "funding opportunit", "notice of funding", "nofo", "notice of special interest",
    "nosi", "request for applications", "rfa-", "par-", "fellowship application",
    "small business innovation", "sbir", "sttr",
]


def _is_funding_item(item: dict) -> bool:
    if item.get("type") == "Funding Opportunity":
        return True
    title = (item.get("title") or "").lower()
    return any(m in title for m in _FUNDING_TITLE_MARKERS)
