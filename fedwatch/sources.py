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
# Browser-like UA: grants.nih.gov (Akamai) rejects bot-looking user agents
# with 403, which silently emptied the NIH notices feed.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, application/json, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Search terms used against the Federal Register full-text API - quoted
# phrases drawn from the SVPR topic domains (fedwatch.topics). An unquoted
# query matches documents containing ANY single word.
FEDERAL_REGISTER_TERMS = (
    '"indirect cost" | "facilities and administrative" | "salary cap" | '
    '"uniform guidance" | "federal financial assistance" | '
    '"research security" | "foreign subaward" | "export control" | '
    '"human subjects" | "institutional review board" | "common rule" | '
    '"animal welfare" | "select agent" | "research misconduct" | '
    '"research integrity" | "scientific integrity" | "data sharing" | '
    '"public access" | "peer review" | "federally funded research" | '
    '"research project grants" | "extramural research"'
)

# NIH Guide has separate feeds: notices.xml carries policy/administrative
# notices (the government-affairs signal); fundingopps.xml carries NOFOs.
NIH_GUIDE_NOTICES_RSS = "https://grants.nih.gov/grants/guide/newsfeed/notices.xml"
NIH_GUIDE_FUNDING_RSS = "https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml"
NIH_NEXUS_RSS = "https://nexus.od.nih.gov/all/feed/"
NSF_NEWS_RSS = "https://www.nsf.gov/rss/rss_www_news.xml"

# Topic screen applied to presidential documents at the source: only
# executive actions touching the research enterprise are kept. Whole-word
# regex - a substring screen matched "grant" inside "Granting Pardon".
_PRESDOC_TOPIC_RE = re.compile(
    r"\b(research|science|scientif\w*|universit\w*|higher education|"
    r"grants?|biomedical|federal funding|national institutes|laborator\w*)\b",
    re.IGNORECASE,
)


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
            headers=FETCH_HEADERS,
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
            headers={**FETCH_HEADERS, "Content-Type": "application/json"},
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
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=TIMEOUT)
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


_NOTICE_LINK_RE = re.compile(
    r'href="([^"]*notice-files/(NOT-[A-Z0-9]+-\d{2}-\d+)\.html?)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def fetch_nih_weekly_index(errors: list | None = None, weeks: int = 6) -> list:
    """Scrape the NIH Guide Weekly Index pages for notices.

    This is the authoritative listing of every NIH Guide notice. Used as the
    primary notices source because NIH's documented RSS only covers funding
    opportunities.
    """
    items, seen = [], set()
    today = datetime.now()
    friday = today - timedelta(days=(today.weekday() - 4) % 7)
    for w in range(weeks):
        week_end = friday - timedelta(weeks=w)
        url = ("https://grants.nih.gov/grants/guide/WeeklyIndex.cfm"
               f"?WeekEnding={week_end.strftime('%m-%d-%Y')}")
        try:
            resp = requests.get(url, headers=FETCH_HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            for href, num, anchor in _NOTICE_LINK_RE.findall(resp.text):
                num = num.upper()
                if num in seen:
                    continue
                seen.add(num)
                title = re.sub(r"\s+", " ", _strip_html(anchor)).strip()
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = f"https://grants.nih.gov{href}"
                else:
                    link = f"https://grants.nih.gov/grants/guide/{href}"
                items.append({
                    "id": f"nih-{num}",
                    "source": "NIH Guide",
                    "agency": "National Institutes of Health",
                    "title": title or num,
                    "summary": f"NIH Guide notice {num} (week ending {week_end.strftime('%Y-%m-%d')}).",
                    "url": link,
                    "date": week_end.strftime("%Y-%m-%d"),
                    "type": "Policy Notice",
                })
        except Exception as e:  # noqa: BLE001
            if errors is not None:
                errors.append(f"NIH Weekly Index ({week_end.strftime('%m-%d')}): {e}")
    if not items:
        # Fallback: the mobile index serves the current week without params.
        try:
            resp = requests.get("https://grants.nih.gov/grants/guide/WeeklyIndexMobile.cfm",
                                headers=FETCH_HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            for href, num, anchor in _NOTICE_LINK_RE.findall(resp.text):
                num = num.upper()
                if num in seen:
                    continue
                seen.add(num)
                title = re.sub(r"\s+", " ", _strip_html(anchor)).strip()
                link = href if href.startswith("http") else f"https://grants.nih.gov{href if href.startswith('/') else '/grants/guide/' + href}"
                items.append({
                    "id": f"nih-{num}", "source": "NIH Guide",
                    "agency": "National Institutes of Health",
                    "title": title or num, "summary": f"NIH Guide notice {num}.",
                    "url": link, "date": datetime.now().strftime("%Y-%m-%d"),
                    "type": "Policy Notice",
                })
        except Exception as e:  # noqa: BLE001
            if errors is not None:
                errors.append(f"NIH Weekly Index (mobile): {e}")
    return items


def fetch_nih_notice_pages(notice_ids: list, errors: list | None = None) -> list:
    """Fetch specific NIH Guide notices directly by number (pinned tracking).

    Guarantees designated notices appear regardless of feed behavior.
    """
    items = []
    for raw in notice_ids:
        nid = (raw or "").strip().upper().rstrip(".HTML").rstrip(".")
        if not nid:
            continue
        url = f"https://grants.nih.gov/grants/guide/notice-files/{nid}.html"
        try:
            resp = requests.get(url, headers=FETCH_HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            m = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", _strip_html(m.group(1))).strip() if m else nid
            items.append({
                "id": f"nih-{nid}",
                "source": "NIH Guide",
                "agency": "National Institutes of Health",
                "title": title,
                "summary": f"Pinned notice {nid} - tracked explicitly.",
                "url": url,
                "date": "",
                "type": "Tracked Notice",
                "watchlist_targeted": True,  # never filtered
            })
        except Exception as e:  # noqa: BLE001
            if errors is not None:
                errors.append(f"NIH notice {nid}: {e}")
    return items


def fetch_nih_notices(errors: list | None = None) -> list:
    """NIH Guide notices: Weekly Index scrape first, RSS as secondary."""
    items = fetch_nih_weekly_index(errors=errors)
    if items:
        return items
    return _fetch_rss(NIH_GUIDE_NOTICES_RSS, "NIH Guide", "National Institutes of Health",
                      errors, item_type="Policy Notice")


def fetch_nih_funding(errors: list | None = None) -> list:
    return _fetch_rss(NIH_GUIDE_FUNDING_RSS, "NIH Guide", "National Institutes of Health",
                      errors, item_type="Funding Opportunity")


def fetch_nsf_news(errors: list | None = None) -> list:
    return _fetch_rss(NSF_NEWS_RSS, "NSF News", "National Science Foundation", errors)


# Agencies whose every Federal Register document matters to an NIH-heavy
# biomedical portfolio - swept without keyword filtering so nothing that the
# term query misses falls through. (FR API agency slugs.)
KEY_AGENCY_SLUGS = [
    "national-institutes-of-health",
    "national-science-foundation",
    "science-and-technology-policy-office",
    "management-and-budget-office",
    "health-and-human-services-department",
    "energy-department",
    "defense-department",
    "national-aeronautics-and-space-administration",
    "food-and-drug-administration",
    "centers-for-disease-control-and-prevention",
]


def fetch_fr_key_agencies(days_back: int = 14, errors: list | None = None) -> list:
    """All recent Federal Register documents from NIH, NSF, OSTP, and OMB."""
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://www.federalregister.gov/api/v1/documents.json",
            params={
                "conditions[agencies][]": KEY_AGENCY_SLUGS,
                "conditions[publication_date][gte]": since,
                "per_page": 40,
                "order": "newest",
                "fields[]": ["title", "abstract", "html_url", "publication_date",
                             "agencies", "type", "document_number"],
            },
            headers=FETCH_HEADERS,
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
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"Federal Register (key agencies): {e}")
        return []


def fetch_executive_orders(days_back: int = 30, errors: list | None = None) -> list:
    """Presidential documents (executive orders, memoranda) touching research.

    Topic-screened at the source: proclamations and EOs unrelated to the
    research enterprise are not returned.
    """
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://www.federalregister.gov/api/v1/documents.json",
            params={
                "conditions[type][]": "PRESDOCU",
                "conditions[publication_date][gte]": since,
                "per_page": 40,
                "order": "newest",
                "fields[]": ["title", "abstract", "html_url", "publication_date",
                             "agencies", "type", "document_number", "subtype"],
            },
            headers=FETCH_HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = []
        for doc in resp.json().get("results", []):
            text = f"{doc.get('title', '')} {doc.get('abstract') or ''}"
            if not _PRESDOC_TOPIC_RE.search(text):
                continue
            subtype = doc.get("subtype") or "Presidential Document"
            items.append({
                "id": f"fr-{doc.get('document_number')}",
                "source": "Federal Register",
                "agency": "Executive Office of the President",
                "title": doc.get("title", ""),
                # Lead with the document kind so the Executive actions topic
                # domain matches and the item floors at CRITICAL.
                "summary": f"Presidential document ({subtype}). {doc.get('abstract') or ''}".strip(),
                "url": doc.get("html_url", ""),
                "date": _norm_date(doc.get("publication_date", "")),
                "type": subtype,
            })
        return items
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"Executive orders: {e}")
        return []


def fetch_nih_nexus(errors: list | None = None) -> list:
    """NIH Extramural Nexus blog - OER policy implementation news."""
    return _fetch_rss(NIH_NEXUS_RSS, "NIH Nexus", "National Institutes of Health",
                      errors, item_type="OER Update")


def fetch_regulations_gov(errors: list | None = None, days_back: int = 14) -> list:
    """Recent regulations.gov documents on federally funded research.

    Uses the public v4 API; REGULATIONS_GOV_API_KEY env var if set, else the
    rate-limited DEMO_KEY.
    """
    import os

    api_key = os.environ.get("REGULATIONS_GOV_API_KEY", "DEMO_KEY")
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://api.regulations.gov/v4/documents",
            params={
                "filter[searchTerm]": '"federally funded research"',
                "filter[postedDate][ge]": since,
                "sort": "-postedDate",
                "page[size]": 25,
                "api_key": api_key,
            },
            headers=FETCH_HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = []
        for doc in resp.json().get("data", []):
            attrs = doc.get("attributes", {}) or {}
            items.append({
                "id": f"regs-{doc.get('id')}",
                "source": "Regulations.gov",
                "agency": attrs.get("agencyId", "Unknown"),
                "title": attrs.get("title", ""),
                "summary": (attrs.get("docketAbstract") or attrs.get("summary") or "")[:800],
                "url": f"https://www.regulations.gov/document/{doc.get('id')}",
                "date": _norm_date((attrs.get("postedDate") or "")[:10]),
                "type": attrs.get("documentType", "Document"),
            })
        return items
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"Regulations.gov: {e}")
        return []


_OMB_MEMO_RE = re.compile(
    r'href="([^"]*?/(?:M|m)-(\d{2})-(\d{2,3})[^"]*)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def fetch_omb_memoranda(errors: list | None = None) -> list:
    """Scrape OMB's memoranda page for recent M-memos (M-26-xx...)."""
    try:
        resp = requests.get(
            "https://www.whitehouse.gov/omb/information-for-agencies/memoranda/",
            headers=FETCH_HEADERS, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items, seen = [], set()
        for href, yy, num, anchor in _OMB_MEMO_RE.findall(resp.text):
            memo_id = f"M-{yy}-{num}"
            if memo_id in seen:
                continue
            title = re.sub(r"\s+", " ", _strip_html(anchor)).strip()
            # Guard against nav/footer links the regex may catch: a real memo
            # link carries the memo id or a substantive title.
            if not re.search(r"\bM-\d{2}-\d+\b", title, re.IGNORECASE) and len(title) < 15:
                continue
            seen.add(memo_id)
            link = href if href.startswith("http") else f"https://www.whitehouse.gov{href}"
            items.append({
                "id": f"omb-{memo_id}",
                "source": "OMB Memoranda",
                "agency": "Office of Management and Budget",
                "title": title or memo_id,
                "summary": f"OMB memorandum {memo_id}.",
                "url": link,
                "date": "",
                "type": "Memorandum",
            })
        return items[:10]  # most recent memos listed first
    except Exception as e:  # noqa: BLE001
        if errors is not None:
            errors.append(f"OMB Memoranda: {e}")
        return []


# Press outlets research offices actually read. General feeds, so items are
# screened for federal research policy relevance at the source.
PRESS_FEEDS = [
    ("https://www.science.org/rss/news_current.xml", "Science (AAAS)"),
    ("https://www.nature.com/nature.rss", "Nature"),
    ("https://www.insidehighered.com/rss.xml", "Inside Higher Ed"),
    ("https://www.statnews.com/feed/", "STAT News"),
]

_PRESS_RESEARCH_RE = re.compile(
    r"\b(research|science|scientists?|nih|nsf|universit\w+|academ\w+|biomedical)\b",
    re.IGNORECASE)
_PRESS_FEDERAL_RE = re.compile(
    r"\b(nih|nsf|doe|federal|congress|white house|trump administration|"
    r"appropriations?|funding|grants?|indirect cost|executive order|hhs|fda|cdc|"
    r"budget|polic(y|ies))\b", re.IGNORECASE)


def fetch_press(errors: list | None = None) -> list:
    """Press coverage of federal research policy from major outlets."""
    items = []
    for url, name in PRESS_FEEDS:
        for it in _fetch_rss(url, name, name, errors, item_type="Press Coverage"):
            text = f"{it.get('title', '')} {it.get('summary', '')}"
            if _PRESS_RESEARCH_RE.search(text) and _PRESS_FEDERAL_RE.search(text):
                items.append(it)
    return items


def fetch_watchlist_targeted(watchlist: list, errors: list | None = None,
                             days_back: int = 90) -> list:
    """Dedicated Federal Register search for the team's watchlist terms.

    Guarantees watched topics are found even when they fall outside the main
    query's phrasing or lookback window. Matches are flagged so downstream
    filters never drop them.
    """
    watch = [w.strip().lower() for w in watchlist if w and w.strip()]
    terms = " | ".join(f'"{w}"' for w in watch)
    if not terms:
        return []
    items = fetch_federal_register(days_back=days_back, errors=errors, terms=terms)
    # The FR API matches FULL DOCUMENT TEXT - "indirect cost" appears in the
    # cost-analysis boilerplate of virtually every fee-setting rule (IRS user
    # fees, SEC rules...). Keep a match only when the watched term appears in
    # the title or abstract, where it signals the document's actual subject.
    kept = []
    for it in items:
        head = f"{it.get('title', '')} {it.get('summary', '')}".lower()
        if any(w in head for w in watch):
            it["watchlist_targeted"] = True
            kept.append(it)
    return kept


def fetch_all(days_back: int = 14, grants_keyword: str = "research",
              include_funding: bool = False, include_news: bool = False,
              include_press: bool = True,
              watchlist: list | None = None, tracked_notices: list | None = None):
    """Fetch every source. Returns (items, errors, used_sample_data).

    Default focus is research policy / government affairs: Federal Register
    documents and NIH policy notices. Funding-opportunity sources (Grants.gov,
    NIH NOFO feed) require include_funding; agency press releases (NSF News:
    podcasts, discovery stories, award announcements) require include_news.
    """
    errors: list[str] = []
    items = []
    # Federal Register is the reliable backbone: full-text policy search plus
    # an agency sweep (every NIH/NSF/DOE/DOD/HHS/OSTP/OMB document). The AI
    # review handles the volume; this keeps coverage even when NIH's own
    # site blocks server-side scraping.
    items += fetch_federal_register(days_back=days_back, errors=errors)
    items += fetch_fr_key_agencies(days_back=days_back, errors=errors)
    items += fetch_executive_orders(errors=errors)
    items += fetch_nih_notices(errors=errors)
    items += fetch_nih_nexus(errors=errors)
    items += fetch_regulations_gov(errors=errors, days_back=days_back)
    items += fetch_omb_memoranda(errors=errors)
    if include_press:
        items += fetch_press(errors=errors)
    if include_news:
        items += fetch_nsf_news(errors=errors)
    if include_funding:
        items += fetch_grants_gov(keyword=grants_keyword, errors=errors)
        items += fetch_nih_funding(errors=errors)

    targeted = fetch_watchlist_targeted(watchlist or [], errors=errors)
    targeted += fetch_nih_notice_pages(tracked_notices or [], errors=errors)
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
