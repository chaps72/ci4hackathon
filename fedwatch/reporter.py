"""NIH RePORTER award fetcher and analytics for the weekly funding report.

NIH RePORTER (https://api.reporter.nih.gov/) is a free, no-key API that returns
funded NIH/HHS project records. You POST a criteria payload to the v2 search
endpoint and get back award details (PI, organization, amount, dates, abstract).

This module supports a rich set of search dimensions - organization, PI name,
research terms, administering Institute/Center (IC), activity code (R01/R21/...),
state, award-size range, fiscal year, and a "newly added" flag - plus analytics
helpers (aggregates, breakdowns, leaderboards) and a peer-institution comparison.

Records are normalized to the same dict shape the rest of FedWatch uses
(id/source/agency/level/title/summary/url/date), with extra structured fields
(pi, org, amount, ic, activity_code, app_type, state, ...) for the dashboard,
so awards plug straight into the existing summary and email-digest machinery.

Every call fails soft: it returns ``(items, error)`` and never raises, so one
unreachable API never takes down the dashboard. The app falls back to a small
bundled sample (``sample_awards``) when the live API is unreachable.
"""

import re
import statistics
from collections import Counter
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
MAX_LIMIT = 500  # RePORTER caps a single page at 500 records.

INCLUDE_FIELDS = [
    "ProjectNum", "CoreProjectNum", "SubprojectId", "ProjectTitle", "AbstractText",
    "FiscalYear", "AwardAmount", "AwardNoticeDate", "ProjectStartDate",
    "ProjectEndDate", "Organization", "PrincipalInvestigators", "ContactPiName",
    "AgencyIcAdmin", "ProjectDetailUrl", "Terms",
]

# ---------------------------------------------------------------------------
# Search vocabularies for the UI dropdowns.
# ---------------------------------------------------------------------------
# Common NIH administering Institutes & Centers (abbreviation -> full name).
IC_CHOICES = {
    "NCI": "National Cancer Institute",
    "NIAID": "Allergy and Infectious Diseases",
    "NHLBI": "Heart, Lung, and Blood",
    "NIGMS": "General Medical Sciences",
    "NIDDK": "Diabetes, Digestive & Kidney",
    "NINDS": "Neurological Disorders and Stroke",
    "NIMH": "Mental Health",
    "NIA": "Aging",
    "NICHD": "Child Health & Human Development",
    "NIDA": "Drug Abuse",
    "NEI": "Eye Institute",
    "NIAMS": "Arthritis, Musculoskeletal & Skin",
    "NIDCR": "Dental & Craniofacial Research",
    "NIDCD": "Deafness & Communication Disorders",
    "NIEHS": "Environmental Health Sciences",
    "NHGRI": "Human Genome Research",
    "NIAAA": "Alcohol Abuse and Alcoholism",
    "NIBIB": "Biomedical Imaging & Bioengineering",
    "NIMHD": "Minority Health & Health Disparities",
    "NINR": "Nursing Research",
    "NLM": "National Library of Medicine",
    "NCATS": "Advancing Translational Sciences",
    "NCCIH": "Complementary & Integrative Health",
    "FIC": "Fogarty International Center",
    "OD": "Office of the Director",
}

# Common activity (mechanism) codes, grouped for the dropdown.
ACTIVITY_CHOICES = {
    "R01": "Research Project Grant",
    "R21": "Exploratory/Developmental",
    "R03": "Small Research Grant",
    "R00": "Career Transition (independent)",
    "R35": "Outstanding Investigator",
    "R37": "MERIT Award",
    "R15": "Academic Research Enhancement (AREA)",
    "U01": "Research Project Cooperative Agreement",
    "U54": "Specialized Center Cooperative",
    "P01": "Program Project",
    "P30": "Center Core Grant",
    "P50": "Specialized Center",
    "K99": "Career Transition (mentored)",
    "K08": "Mentored Clinical Scientist",
    "K23": "Mentored Patient-Oriented",
    "K01": "Mentored Research Scientist",
    "F31": "Predoctoral Fellowship",
    "F32": "Postdoctoral Fellowship",
    "T32": "Institutional Training Grant",
    "DP2": "New Innovator Award",
    "UG3": "Phased Cooperative (UG3)",
    "UH3": "Phased Cooperative (UH3)",
}

# First character of an NIH project number encodes the application type.
APP_TYPE = {
    "1": "New", "2": "Renewal", "3": "Supplement", "4": "Extension",
    "5": "Continuation", "6": "Continuation", "7": "Transfer", "9": "IC transfer",
}

_PNUM_RE = re.compile(r"^\s*(\d)?\s*([A-Za-z][A-Za-z0-9]{2})")


def parse_project_num(project_num: str):
    """Return (application_type_label, activity_code) parsed from a project num.

    e.g. "5R01AI123456-03" -> ("Continuation", "R01");
         "1DP2OD098765-01" -> ("New", "DP2").
    """
    m = _PNUM_RE.match(project_num or "")
    if not m:
        return "", ""
    app = APP_TYPE.get(m.group(1) or "", "")
    return app, (m.group(2) or "").upper()


def _payload(org_names, pi_name, text_query, ic_codes, activity_codes, org_states,
             award_min, award_max, from_date, to_date, fiscal_years,
             newly_added_only, offset, limit, active_only=False):
    criteria: dict = {}
    if active_only:
        # Include projects whose award period is current (not just those with a
        # recent award-notice date). Results are still date/period-filtered below.
        criteria["include_active_projects"] = True
    if org_names:
        criteria["org_names"] = list(org_names)
    if pi_name:
        criteria["pi_names"] = [{"any_name": pi_name}]
    if text_query:
        criteria["advanced_text_search"] = {
            "operator": "and", "search_field": "all", "search_text": text_query,
        }
    if ic_codes:
        criteria["agencies"] = list(ic_codes)
    if activity_codes:
        criteria["activity_codes"] = list(activity_codes)
    if org_states:
        criteria["org_states"] = [s.upper() for s in org_states]
    if award_min is not None or award_max is not None:
        rng = {}
        if award_min is not None:
            rng["min_amount"] = int(award_min)
        if award_max is not None:
            rng["max_amount"] = int(award_max)
        criteria["award_amount_range"] = rng
    if from_date and to_date:
        criteria["award_notice_date"] = {"from_date": from_date, "to_date": to_date}
    if fiscal_years:
        criteria["fiscal_years"] = list(fiscal_years)
    if newly_added_only:
        criteria["newly_added_projects_only"] = True
    return {
        "criteria": criteria,
        "include_fields": INCLUDE_FIELDS,
        "offset": offset,
        "limit": min(limit, MAX_LIMIT),
        "sort_field": "award_notice_date",
        "sort_order": "desc",
    }


def _pis(rec: dict) -> list:
    """List of PD/PIs as {name, contact}. Marks the contact PI; if the API
    doesn't flag one (e.g. a single-PI grant), the first PI is the contact."""
    out = []
    for p in rec.get("principal_investigators") or []:
        name = (p.get("full_name") or "").strip()
        if not name:
            name = f"{(p.get('first_name') or '').strip()} {(p.get('last_name') or '').strip()}".strip()
        if name and not any(o["name"] == name for o in out):
            out.append({"name": name, "contact": bool(p.get("is_contact_pi"))})
    if not out:
        contact = (rec.get("contact_pi_name") or "").strip()
        if contact:
            out.append({"name": contact, "contact": True})
    if out and not any(p["contact"] for p in out):
        out[0]["contact"] = True
    return out


def _pi_list(rec: dict) -> list:
    return [p["name"] for p in _pis(rec)]


def _pi_names(rec: dict) -> str:
    return ", ".join(_pi_list(rec))


def fmt_money(amount) -> str:
    try:
        return f"${int(amount):,}"
    except (TypeError, ValueError):
        return "—"


def _normalize(rec: dict) -> dict:
    org = rec.get("organization") or {}
    ic = rec.get("agency_ic_admin") or {}
    pis = _pis(rec)
    pis_names = [p["name"] for p in pis]
    pi = ", ".join(pis_names)
    contact_pi = next((p["name"] for p in pis if p["contact"]),
                      pis_names[0] if pis_names else "")
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
    app_type, activity_code = parse_project_num(project_num)
    # The core project number identifies a grant across its fiscal-year records,
    # so multi-year pulls don't count one grant several times. Derive it from the
    # full project number when RePORTER doesn't supply it.
    core_num = (rec.get("core_project_num") or "").strip().upper()
    if not core_num and project_num:
        core_num = re.sub(r"^\s*\d+", "", project_num).split("-")[0].strip().upper()
    # Per-fiscal-year funding for this record, preserved through dedupe so
    # year-by-year breakdowns (and charts) remain possible.
    fy_amounts = {}
    if rec.get("fiscal_year") is not None and amount is not None:
        fy_amounts[rec["fiscal_year"]] = _toint(amount)

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
        "project_num": project_num,
        "core_num": core_num,
        "pi": pi,
        "pi_list": pis_names,
        "pis": pis,
        "contact_pi": contact_pi,
        "multi_pi": len(pis) > 1,
        "is_subproject": bool(rec.get("subproject_id")),
        "org": org_name,
        "amount": amount,
        "fiscal_year": rec.get("fiscal_year"),
        "fy_amounts": fy_amounts,
        "ic": agency,
        "activity_code": activity_code,
        "app_type": app_type,
        "city": (org.get("org_city") or "").strip(),
        "state": (org.get("org_state") or "").strip(),
        "award_date": award_date,
        "start": start,
        "end": end,
        "abstract": abstract,
    }


def fetch_awards(org_names=None, pi_name: str = "", text_query: str = "",
                 ic_codes=None, activity_codes=None, org_states=None,
                 award_min=None, award_max=None, days_back: int = 7,
                 fiscal_years=None, newly_added_only: bool = False,
                 limit: int = 200, use_award_window: bool = True,
                 active_only: bool = False):
    """Fetch recent NIH awards. Returns ``(items, error)``; never raises.

    ``items`` is a list of normalized dicts (newest award first). ``error`` is
    None on success (even when zero awards match) or a short message when the
    live API could not be reached. With ``active_only`` the result is restricted
    to grants whose project period is current (end date today or later), and the
    day look-back is ignored so the whole active portfolio is considered.
    """
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=max(days_back, 1))).strftime("%Y-%m-%d")
    # Active-grant queries span the portfolio, not a recent-notice window.
    window = use_award_window and not active_only

    def build(offset, page):
        return _payload(
            org_names=org_names, pi_name=pi_name.strip(),
            text_query=text_query.strip(), ic_codes=ic_codes,
            activity_codes=activity_codes, org_states=org_states,
            award_min=award_min, award_max=award_max,
            from_date=from_date if window else None,
            to_date=to_date if window else None,
            fiscal_years=fiscal_years, newly_added_only=newly_added_only,
            offset=offset, limit=page, active_only=active_only)

    # Page through results so large pulls (e.g. a full fiscal year for
    # investigator-level analysis) aren't truncated at the 500-record page cap.
    records: list = []
    offset, total = 0, None
    while len(records) < limit:
        page = min(MAX_LIMIT, limit - len(records))
        try:
            resp = requests.post(API_URL, json=build(offset, page),
                                 headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - fail soft
            if records:
                break  # keep what we already have
            return [], f"NIH RePORTER fetch failed: {exc}"
        results = data.get("results") or []
        records.extend(results)
        total = (data.get("meta") or {}).get("total", total)
        offset += len(results)
        if not results or (total is not None and offset >= total) or offset >= 14000:
            break

    items = [_normalize(r) for r in records]
    if active_only:
        # Keep grants whose period is current: end date today or later (records
        # without an end date are treated as active).
        items = [it for it in items if not it.get("end") or it["end"] >= to_date]
    # Collapse fiscal-year records to one row per distinct grant so multi-year
    # pulls don't count a single grant (or a PI's grant) several times.
    items = dedupe_projects(items)
    items.sort(key=lambda i: i.get("award_date") or i.get("start") or "", reverse=True)
    return items, None


def _toint(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def dedupe_projects(items: list) -> list:
    """Collapse RePORTER's per-fiscal-year rows to one row per distinct grant.

    Grants are identified by core project number. The most recent fiscal-year
    record represents the grant; its ``amount`` becomes the total awarded across
    the records in the pulled window (so dollars aren't lost), and
    ``years_in_window`` lists the fiscal years seen.
    """
    groups: dict = {}
    order: list = []
    for idx, it in enumerate(items):
        key = it.get("core_num") or it.get("project_num") or f"_uniq{idx}"
        groups.setdefault(key, []).append(it)
        if len(groups[key]) == 1:
            order.append(key)
    out = []
    for key in order:
        group = groups[key]
        rep = dict(max(group, key=lambda i: ((i.get("fiscal_year") or 0),
                                             i.get("award_date") or "")))
        # Merge per-fiscal-year funding across the grant's records, preserving
        # the year-by-year breakdown while the grant is counted once.
        fy_amounts: dict = {}
        for i in group:
            for fy, amt in (i.get("fy_amounts") or {}).items():
                fy_amounts[fy] = fy_amounts.get(fy, 0) + amt
        rep["fy_amounts"] = fy_amounts
        rep["amount"] = sum(fy_amounts.values()) or rep.get("amount")
        rep["years_in_window"] = sorted(fy_amounts.keys())
        out.append(rep)
    return out


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def _amounts(items: list) -> list:
    out = []
    for it in items:
        try:
            out.append(int(it["amount"]))
        except (TypeError, ValueError, KeyError):
            pass
    return out


def _sum_by(items: list, key: str) -> dict:
    """Total award dollars grouped by ``key`` (descending)."""
    out: dict = {}
    for it in items:
        val = it.get(key) or "—"
        out[val] = out.get(val, 0) + _toint(it.get("amount"))
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def _funding_by_fy(items: list) -> dict:
    """Total dollars per fiscal year (chronological), from per-year amounts."""
    out: dict = {}
    for it in items:
        for fy, amt in (it.get("fy_amounts") or {}).items():
            out[fy] = out.get(fy, 0) + amt
    return dict(sorted(out.items()))


def funding_crosstab(items: list, key: str) -> dict:
    """Per-category, per-fiscal-year funding: ``{category: {fiscal_year: dollars}}``.

    Powers year-over-year comparisons (e.g. funding by institute across years).
    """
    out: dict = {}
    for it in items:
        cat = it.get(key) or "—"
        for fy, amt in (it.get("fy_amounts") or {}).items():
            out.setdefault(cat, {})[fy] = out.setdefault(cat, {}).get(fy, 0) + amt
    return out


def _counts(items: list, key: str) -> dict:
    out: dict = {}
    for it in items:
        val = it.get(key) or "—"
        out[val] = out.get(val, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def aggregate(items: list) -> dict:
    """Headline stats and breakdowns for the report."""
    amts = _amounts(items)
    total = sum(amts)
    return {
        "count": len(items),
        "total_amount": total,
        "amount_known": len(amts),
        "median_amount": int(statistics.median(amts)) if amts else 0,
        "mean_amount": int(statistics.mean(amts)) if amts else 0,
        "max_amount": max(amts) if amts else 0,
        "by_ic": _counts(items, "ic"),
        "by_activity": _counts(items, "activity_code"),
        "by_app_type": _counts(items, "app_type"),
        "by_state": _counts(items, "state"),
        "by_fy": dict(sorted(_counts(items, "fiscal_year").items())),
        "by_org": _counts(items, "org"),
        # Funding ($) breakdowns for every dimension, so any "by X" question or
        # chart works for dollars as well as counts.
        "funding_by_fy": _funding_by_fy(items),
        "funding_by_ic": _sum_by(items, "ic"),
        "funding_by_activity": _sum_by(items, "activity_code"),
        "funding_by_app_type": _sum_by(items, "app_type"),
        "funding_by_state": _sum_by(items, "state"),
        "funding_by_org": _sum_by(items, "org"),
    }


def leaderboard(items: list, key: str, n: int = 10) -> list:
    """Top ``n`` values of ``key`` ranked by total award dollars.

    Returns a list of {name, awards, total_amount} dicts.
    """
    rollup: dict = {}
    for it in items:
        name = it.get(key) or "—"
        bucket = rollup.setdefault(name, {"awards": 0, "total_amount": 0})
        bucket["awards"] += 1
        try:
            bucket["total_amount"] += int(it["amount"])
        except (TypeError, ValueError, KeyError):
            pass
    rows = [{"name": k, **v} for k, v in rollup.items()]
    rows.sort(key=lambda r: (r["total_amount"], r["awards"]), reverse=True)
    return rows[:n]


def pi_award_counts(items: list) -> Counter:
    """Count awards per individual investigator (each listed PI on an award).

    A multi-PI award counts once for each of its principal investigators.
    """
    counts: Counter = Counter()
    for it in items:
        names = it.get("pi_list") or ([it["pi"]] if it.get("pi") else [])
        for name in names:
            counts[name] += 1
    return counts


def pi_role_counts(items: list) -> dict:
    """Per investigator, distinct grants split by role.

    Returns ``{name: {"total": n, "contact": n, "copi": n}}`` where ``contact``
    counts grants where the person is the contact PI and ``copi`` counts grants
    where they are an additional PI on a multi-PI grant (co-PI / MPI). NIH
    RePORTER publishes PD/PIs only - co-investigators are not in the data.
    """
    roles: dict = {}
    for it in items:
        core = it.get("core_num") or it.get("project_num") or it.get("id")
        for p in it.get("pis") or []:
            r = roles.setdefault(p["name"], {"contact": set(), "copi": set()})
            (r["contact"] if p.get("contact") else r["copi"]).add(core)
    out = {}
    for name, r in roles.items():
        out[name] = {"total": len(r["contact"] | r["copi"]),
                     "contact": len(r["contact"]), "copi": len(r["copi"])}
    return dict(sorted(out.items(), key=lambda kv: kv[1]["total"], reverse=True))


def grant_count_distribution(items: list, thresholds=(1, 2, 3, 4, 5)) -> dict:
    """How many investigators hold at least N grants as PI, for each N.

    Returns ``{"counts": Counter, "at_least": {N: num_investigators}}``.
    """
    counts = pi_award_counts(items)
    at_least = {t: sum(1 for n in counts.values() if n >= t) for t in thresholds}
    return {"counts": counts, "at_least": at_least}


def compare_orgs(orgs, text_query: str = "", ic_codes=None, days_back: int = 7,
                 fiscal_years=None, limit: int = 400):
    """Fetch awards for several organizations and return comparable aggregates.

    Returns ``(rows, errors)`` where rows is a list of
    {org, awards, total_amount, median_amount} (live data required).
    """
    rows, errors = [], []
    for org in orgs:
        org = org.strip()
        if not org:
            continue
        items, err = fetch_awards(
            org_names=[org], text_query=text_query, ic_codes=ic_codes,
            days_back=days_back, fiscal_years=fiscal_years, limit=limit)
        if err:
            errors.append(f"{org}: {err}")
            continue
        agg = aggregate(items)
        rows.append({
            "org": org,
            "awards": agg["count"],
            "total_amount": agg["total_amount"],
            "median_amount": agg["median_amount"],
        })
    rows.sort(key=lambda r: r["total_amount"], reverse=True)
    return rows, errors


# ---------------------------------------------------------------------------
# Offline sample so the report renders without network access. Figures are
# illustrative, not real award records. Varied IC / activity / application type
# so every breakdown and leaderboard is populated in the demo.
# ---------------------------------------------------------------------------
def _s(pnum, title, abstract, amount, notice, start, end, ic, ic_name, pis, oid):
    return {
        "project_num": pnum, "project_title": title, "abstract_text": abstract,
        "fiscal_year": 2026, "award_amount": amount, "award_notice_date": notice,
        "project_start_date": start, "project_end_date": end,
        "organization": {"org_name": "EMORY UNIVERSITY", "org_city": "ATLANTA",
                         "org_state": "GA"},
        "principal_investigators": [{"full_name": p} for p in pis],
        "agency_ic_admin": {"abbreviation": ic, "name": ic_name},
        "project_detail_url": f"https://reporter.nih.gov/project-details/{oid}",
    }


SAMPLE_AWARDS = [
    _s("5R01AI123456-03", "Mucosal immunity and broadly protective vaccine platforms",
       "Adjuvanted intranasal vaccine platforms eliciting durable mucosal and systemic "
       "immunity against respiratory pathogens.", 612340, "2026-06-11", "2026-07-01",
       "2027-06-30", "NIAID", "Allergy and Infectious Diseases", ["Rivera, Elena M"], 11000001),
    _s("1R21MH234567-01", "Neural circuits of stress resilience in adolescent depression",
       "Longitudinal neuroimaging identifying prefrontal–limbic markers predicting "
       "resilience to depression after early-life stress.", 421000, "2026-06-10",
       "2026-06-15", "2028-05-31", "NIMH", "Mental Health", ["Okafor, Daniel"], 11000002),
    _s("5U01CA345678-02", "Liquid biopsy biomarkers for early pancreatic cancer detection",
       "Validation of a circulating tumor DNA and protein panel for detecting resectable "
       "pancreatic cancer in high-risk cohorts.", 1284900, "2026-06-09", "2026-07-01",
       "2029-06-30", "NCI", "National Cancer Institute",
       ["Nguyen, Thanh", "Bauer, Sophia"], 11000003),
    _s("5R01HL456789-04", "Single-cell mapping of cardiac fibrosis after infarction",
       "Single-cell and spatial transcriptomics charting fibroblast activation driving "
       "adverse remodeling after heart attack.", 738500, "2026-06-09", "2026-08-01",
       "2027-07-31", "NHLBI", "Heart, Lung, and Blood", ["Patel, Anika"], 11000004),
    _s("1R01AG567890-01", "Sleep, glymphatic clearance, and Alzheimer's disease risk",
       "Testing whether disrupted slow-wave sleep impairs glymphatic clearance of "
       "amyloid-beta and accelerates preclinical Alzheimer's.", 905120, "2026-06-08",
       "2026-09-01", "2031-08-31", "NIA", "Aging", ["Coleman, Marcus"], 11000005),
    _s("1DP2OD678901-01", "New Innovator: programmable RNA sensors in living cells",
       "Engineering programmable RNA sensors that detect intracellular signals and "
       "actuate therapeutic outputs.", 1500000, "2026-06-12", "2026-09-15", "2031-09-14",
       "OD", "Office of the Director", ["Santos, Maria"], 11000006),
    _s("5R01NS789012-02", "Microglial control of synaptic pruning in epilepsy",
       "Defining how microglial signaling reshapes synaptic networks during "
       "epileptogenesis.", 567800, "2026-06-07", "2026-07-01", "2028-06-30", "NINDS",
       "Neurological Disorders and Stroke", ["Hughes, Robert"], 11000007),
    _s("2R01DK890123-06", "Gut microbiome metabolites and insulin resistance",
       "Renewal: defining bacterial metabolites that modulate hepatic insulin "
       "sensitivity in type 2 diabetes.", 681250, "2026-06-06", "2026-08-01",
       "2031-07-31", "NIDDK", "Diabetes, Digestive & Kidney", ["Adeyemi, Grace"], 11000008),
    _s("1K99CA901234-01", "Career transition: spatial immunology of glioblastoma",
       "Mapping spatial immune niches in glioblastoma toward combination "
       "immunotherapy.", 248000, "2026-06-05", "2026-07-01", "2028-06-30", "NCI",
       "National Cancer Institute", ["Lindqvist, Karin"], 11000009),
    _s("5R01EY012345-03", "Retinal organoids for inherited blindness gene therapy",
       "Patient-derived retinal organoids to test base-editing rescue of inherited "
       "photoreceptor degeneration.", 793400, "2026-06-05", "2026-08-01", "2028-07-31",
       "NEI", "Eye Institute", ["Brooks, Daniel"], 11000010),
    # Repeat PIs so investigator grant-count analysis is populated offline:
    # Rivera holds 3 grants as PI; Patel holds 2.
    _s("1R21AI234561-01", "Nanoparticle adjuvants for mucosal vaccine delivery",
       "Engineering nanoparticle adjuvants to enhance durable mucosal immunity.",
       389700, "2026-06-04", "2026-07-01", "2028-06-30", "NIAID",
       "Allergy and Infectious Diseases", ["Rivera, Elena M"], 11000011),
    _s("1U01AI234562-01", "Systems immunology of broadly neutralizing antibody induction",
       "A cooperative study profiling B-cell trajectories toward broadly neutralizing "
       "antibodies across vaccine cohorts.", 1042500, "2026-06-03", "2026-08-01",
       "2031-07-31", "NIAID", "Allergy and Infectious Diseases",
       ["Rivera, Elena M", "Okafor, Daniel"], 11000012),
    _s("2R01HL456790-05", "Mechanotransduction in cardiac fibroblast activation",
       "Renewal: defining how mechanical cues drive fibroblast activation in the "
       "remodeling heart.", 702800, "2026-06-03", "2026-09-01", "2031-08-31", "NHLBI",
       "Heart, Lung, and Blood", ["Patel, Anika"], 11000013),
]


def sample_awards() -> list:
    """Normalized offline sample awards for the demo / unreachable-API path."""
    return [_normalize(r) for r in SAMPLE_AWARDS]
