"""NIH RePORTER award fetcher for the weekly funding report.

NIH RePORTER (https://api.reporter.nih.gov/) is a free, no-key API that returns
funded NIH/HHS project records. You POST a criteria payload to the v2 search
endpoint and get back award details (PI, organization, amount, dates, abstract).

Two modes drive the weekly report:
- ``org_names``  : recent awards to one or more organizations (default: Emory) -
                   the office's own newly funded portfolio.
- ``text_query`` : recent awards across all institutions matching research terms -
                   competitive intelligence.
The two can be combined (Emory awards in a topic area).

Records are normalized to the same dict shape the rest of FedWatch uses
(id/source/agency/level/title/summary/url/date), with extra structured fields
(pi, org, amount, fiscal_year, ic, ...) for the table view, so awards plug
straight into the existing summary and email-digest machinery.

Every call fails soft: it returns ``(items, error)`` and never raises, so one
unreachable API never takes down the dashboard. The app falls back to a small
bundled sample (``SAMPLE_AWARDS``) when the live API is unreachable, so the demo
always works offline.
"""

from datetime import datetime, timedelta

import requests

API_URL = "https://api.reporter.nih.gov/v2/projects/search"
TIMEOUT = 25
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Content-Type": "application/json",
    "Accept": "application/json",
}

DEFAULT_ORG = "EMORY UNIVERSITY"

# Fields requested from the API. RePORTER returns a large record by default;
# limiting the payload keeps responses small and predictable.
INCLUDE_FIELDS = [
    "ProjectNum", "ProjectTitle", "AbstractText", "FiscalYear",
    "AwardAmount", "AwardNoticeDate", "ProjectStartDate", "ProjectEndDate",
    "Organization", "PrincipalInvestigators", "ContactPiName",
    "AgencyIcAdmin", "ProjectDetailUrl", "Terms",
]

# RePORTER caps a single page at 500 records.
MAX_LIMIT = 500


def _payload(org_names, text_query, from_date, to_date, fiscal_years, offset, limit):
    criteria: dict = {}
    if org_names:
        criteria["org_names"] = org_names
    if text_query:
        criteria["advanced_text_search"] = {
            "operator": "and",
            "search_field": "projecttitle,terms,abstracttext",
            "search_text": text_query,
        }
    if from_date and to_date:
        criteria["award_notice_date"] = {"from_date": from_date, "to_date": to_date}
    if fiscal_years:
        criteria["fiscal_years"] = list(fiscal_years)
    return {
        "criteria": criteria,
        "include_fields": INCLUDE_FIELDS,
        "offset": offset,
        "limit": min(limit, MAX_LIMIT),
        "sort_field": "award_notice_date",
        "sort_order": "desc",
    }


def _pi_names(rec: dict) -> str:
    pis = rec.get("principal_investigators") or []
    names = []
    for p in pis:
        name = (p.get("full_name") or "").strip()
        if not name:
            first = (p.get("first_name") or "").strip()
            last = (p.get("last_name") or "").strip()
            name = f"{first} {last}".strip()
        if name:
            names.append(name)
    if names:
        return ", ".join(names)
    return (rec.get("contact_pi_name") or "").strip()


def fmt_money(amount) -> str:
    try:
        return f"${int(amount):,}"
    except (TypeError, ValueError):
        return "—"


def _normalize(rec: dict) -> dict:
    org = rec.get("organization") or {}
    ic = rec.get("agency_ic_admin") or {}
    pi = _pi_names(rec)
    org_name = (org.get("org_name") or "").strip()
    amount = rec.get("award_amount")
    project_num = (rec.get("project_num") or "").strip()
    agency = (ic.get("abbreviation") or ic.get("name") or "NIH").strip()
    award_date = (rec.get("award_notice_date") or "")[:10]
    start = (rec.get("project_start_date") or "")[:10]
    end = (rec.get("project_end_date") or "")[:10]
    abstract = (rec.get("abstract_text") or "").strip()
    url = (rec.get("project_detail_url") or "").strip()
    if not url and project_num:
        url = f"https://reporter.nih.gov/search/projects?projectNums={project_num}"

    # One-line summary used by the feed cards, summarizer, and email digest.
    bits = [b for b in (
        pi and f"PI: {pi}",
        org_name,
        amount is not None and f"Award: {fmt_money(amount)}",
        (start or end) and f"Period: {start or '?'} – {end or '?'}",
    ) if b]
    summary = " · ".join(bits)
    if abstract:
        summary = (summary + " — " if summary else "") + abstract[:500]

    return {
        "id": project_num or f"reporter-{hash(rec.get('project_title', ''))}",
        "source": "NIH RePORTER",
        "agency": agency,
        "level": "INFO",
        "title": (rec.get("project_title") or "(untitled project)").strip(),
        "summary": summary,
        "url": url,
        "date": award_date or start,
        "type": "NIH award",
        # Structured fields for the table view / aggregates:
        "project_num": project_num,
        "pi": pi,
        "org": org_name,
        "amount": amount,
        "fiscal_year": rec.get("fiscal_year"),
        "ic": agency,
        "city": (org.get("org_city") or "").strip(),
        "state": (org.get("org_state") or "").strip(),
        "award_date": award_date,
        "start": start,
        "end": end,
        "abstract": abstract,
    }


def fetch_awards(org_names=None, text_query: str = "", days_back: int = 7,
                 fiscal_years=None, limit: int = 200, use_award_window: bool = True):
    """Fetch recent NIH awards. Returns ``(items, error)``; never raises.

    ``items`` is a list of normalized dicts (newest award first). ``error`` is
    None on success (even when zero awards match) or a short message when the
    live API could not be reached.
    """
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=max(days_back, 1))).strftime("%Y-%m-%d")
    payload = _payload(
        org_names=org_names,
        text_query=text_query.strip(),
        from_date=from_date if use_award_window else None,
        to_date=to_date if use_award_window else None,
        fiscal_years=fiscal_years,
        offset=0,
        limit=limit,
    )
    try:
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - fail soft, caller falls back to sample
        return [], f"NIH RePORTER fetch failed: {exc}"

    results = data.get("results") or []
    items = [_normalize(r) for r in results]
    # Newest award notices first; records without a date sort last.
    items.sort(key=lambda i: i.get("award_date") or i.get("start") or "", reverse=True)
    return items, None


def aggregate(items: list) -> dict:
    """Summary stats for the report header."""
    total = 0
    counted = 0
    by_ic: dict = {}
    by_org: dict = {}
    for it in items:
        amt = it.get("amount")
        try:
            total += int(amt)
            counted += 1
        except (TypeError, ValueError):
            pass
        ic = it.get("ic") or "?"
        by_ic[ic] = by_ic.get(ic, 0) + 1
        org = it.get("org") or "?"
        by_org[org] = by_org.get(org, 0) + 1
    return {
        "count": len(items),
        "total_amount": total,
        "amount_known": counted,
        "by_ic": dict(sorted(by_ic.items(), key=lambda kv: kv[1], reverse=True)),
        "by_org": dict(sorted(by_org.items(), key=lambda kv: kv[1], reverse=True)),
    }


# ---------------------------------------------------------------------------
# Offline sample so the report renders without network access. Figures are
# illustrative, not real award records.
# ---------------------------------------------------------------------------
SAMPLE_AWARDS = [
    {
        "project_num": "5R01AI123456-03", "project_title":
            "Mucosal immunity and broadly protective vaccine platforms",
        "abstract_text": "This project develops adjuvanted intranasal vaccine "
            "platforms to elicit durable mucosal and systemic immunity against "
            "respiratory pathogens, with an emphasis on broadly protective antigens.",
        "fiscal_year": 2026, "award_amount": 612340,
        "award_notice_date": "2026-06-11", "project_start_date": "2026-07-01",
        "project_end_date": "2027-06-30",
        "organization": {"org_name": "EMORY UNIVERSITY", "org_city": "ATLANTA",
                         "org_state": "GA"},
        "principal_investigators": [{"full_name": "Rivera, Elena M"}],
        "agency_ic_admin": {"abbreviation": "NIAID",
                            "name": "National Institute of Allergy and Infectious Diseases"},
        "project_detail_url": "https://reporter.nih.gov/project-details/11000001",
    },
    {
        "project_num": "1R21MH234567-01", "project_title":
            "Neural circuits of stress resilience in adolescent depression",
        "abstract_text": "A longitudinal neuroimaging study identifying "
            "prefrontal–limbic circuit markers that predict resilience to "
            "depression following early-life stress.",
        "fiscal_year": 2026, "award_amount": 421000,
        "award_notice_date": "2026-06-10", "project_start_date": "2026-06-15",
        "project_end_date": "2028-05-31",
        "organization": {"org_name": "EMORY UNIVERSITY", "org_city": "ATLANTA",
                         "org_state": "GA"},
        "principal_investigators": [{"full_name": "Okafor, Daniel"}],
        "agency_ic_admin": {"abbreviation": "NIMH",
                            "name": "National Institute of Mental Health"},
        "project_detail_url": "https://reporter.nih.gov/project-details/11000002",
    },
    {
        "project_num": "5U01CA345678-02", "project_title":
            "Liquid biopsy biomarkers for early pancreatic cancer detection",
        "abstract_text": "Validation of a multi-analyte circulating tumor DNA and "
            "protein panel for detecting resectable pancreatic ductal "
            "adenocarcinoma in high-risk cohorts.",
        "fiscal_year": 2026, "award_amount": 1284900,
        "award_notice_date": "2026-06-09", "project_start_date": "2026-07-01",
        "project_end_date": "2029-06-30",
        "organization": {"org_name": "EMORY UNIVERSITY", "org_city": "ATLANTA",
                         "org_state": "GA"},
        "principal_investigators": [{"full_name": "Nguyen, Thanh"},
                                    {"full_name": "Bauer, Sophia"}],
        "agency_ic_admin": {"abbreviation": "NCI",
                            "name": "National Cancer Institute"},
        "project_detail_url": "https://reporter.nih.gov/project-details/11000003",
    },
    {
        "project_num": "5R01HL456789-04", "project_title":
            "Single-cell mapping of cardiac fibrosis after myocardial infarction",
        "abstract_text": "Using single-cell and spatial transcriptomics to chart "
            "fibroblast activation states driving adverse remodeling after heart "
            "attack, toward anti-fibrotic targets.",
        "fiscal_year": 2026, "award_amount": 738500,
        "award_notice_date": "2026-06-09", "project_start_date": "2026-08-01",
        "project_end_date": "2027-07-31",
        "organization": {"org_name": "EMORY UNIVERSITY", "org_city": "ATLANTA",
                         "org_state": "GA"},
        "principal_investigators": [{"full_name": "Patel, Anika"}],
        "agency_ic_admin": {"abbreviation": "NHLBI",
                            "name": "National Heart, Lung, and Blood Institute"},
        "project_detail_url": "https://reporter.nih.gov/project-details/11000004",
    },
    {
        "project_num": "1R01AG567890-01", "project_title":
            "Sleep, glymphatic clearance, and Alzheimer's disease risk",
        "abstract_text": "Testing whether disrupted slow-wave sleep impairs "
            "glymphatic clearance of amyloid-beta and accelerates preclinical "
            "Alzheimer's pathology in older adults.",
        "fiscal_year": 2026, "award_amount": 905120,
        "award_notice_date": "2026-06-08", "project_start_date": "2026-09-01",
        "project_end_date": "2031-08-31",
        "organization": {"org_name": "EMORY UNIVERSITY", "org_city": "ATLANTA",
                         "org_state": "GA"},
        "principal_investigators": [{"full_name": "Coleman, Marcus"}],
        "agency_ic_admin": {"abbreviation": "NIA",
                            "name": "National Institute on Aging"},
        "project_detail_url": "https://reporter.nih.gov/project-details/11000005",
    },
]


def sample_awards() -> list:
    """Normalized offline sample awards for the demo / unreachable-API path."""
    return [_normalize(r) for r in SAMPLE_AWARDS]
