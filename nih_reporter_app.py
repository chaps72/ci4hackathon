"""NIH RePORTER Weekly Report - standalone Streamlit app.

A professional weekly report of recently issued NIH/HHS awards, pulled live from
the NIH RePORTER API (https://api.reporter.nih.gov/ - free, no key). Search by
institution, PI, research terms, Institute/Center, activity code, state, and
award size; explore breakdowns, leaderboards, and peer benchmarking; then export
or deliver the report by email, Teams, or Slack.

Runs independently of the FedWatch dashboard; both share fedwatch/reporter.py.

Run with:  streamlit run nih_reporter_app.py
"""

import io
import os
import re
from datetime import datetime

import pandas as pd
import streamlit as st

# Control characters openpyxl rejects in cells (NIH abstracts/titles sometimes
# contain them); strip before writing Excel.
_ILLEGAL_XLSX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

from fedwatch import emailer, notify, reporter, summarize

st.set_page_config(page_title="NIH RePORTER Weekly Report", page_icon="🔬",
                   layout="wide", initial_sidebar_state="collapsed")

# ---------- Apple-inspired styling (system font, airy, ghost buttons) ----------
ACCENT = "#0071e3"        # Apple blue (links, tabs, charts)
ACCENT_HOVER = "#0a84ff"
ACCENT_2 = "#30b0a8"      # secondary chart series
INK = "#1d1d1f"           # Apple near-black text
MUTED = "#6e6e73"         # Apple secondary text
BORDER = "#d2d2d7"        # Apple hairline
PANEL = "#f5f5f7"         # Apple light gray
# Chart colors (names kept for existing references).
EMORY_BLUE = ACCENT
EMORY_LIGHT_BLUE = ACCENT_HOVER
EMORY_GOLD = ACCENT_2

_APPLE_FONT = ("-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', "
               "'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif")

st.markdown(f"""<style>
html, body, [class*="css"], .stMarkdown, p, span, div, input, textarea, button, label {{
    font-family: {_APPLE_FONT};
    -webkit-font-smoothing: antialiased;
}}
h1, h2, h3, h4 {{ color: {INK} !important; font-family: {_APPLE_FONT} !important;
    font-weight: 600 !important; letter-spacing: -0.02em; }}
[data-testid="stAppViewContainer"] {{ background: #ffffff; }}
.block-container {{ padding-top: 2.2rem; max-width: 1100px; }}
[data-testid="stSidebar"] {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
[data-testid="stExpander"] {{
    border: 1px solid {BORDER}; border-radius: 14px; background: #ffffff;
    margin-bottom: 10px; box-shadow: none;
}}
/* All buttons: outlined / ghost pill, fill on hover (Apple-style) */
.stButton button, .stDownloadButton button {{
    background: #ffffff; color: {INK}; border: 1px solid {BORDER};
    border-radius: 980px; font-weight: 500; padding: 0.45rem 1.2rem;
    transition: all 0.15s ease;
}}
.stButton button:hover, .stDownloadButton button:hover,
.stFormSubmitButton button:hover {{
    background: {INK}; color: #ffffff; border-color: {INK};
}}
.stFormSubmitButton button {{
    background: #ffffff; color: {INK}; border: 1px solid {BORDER};
    border-radius: 980px; font-weight: 500;
}}
/* Example chips: smaller ghost pills */
.stButton button[kind="secondary"] {{
    font-size: 0.78rem; padding: 0.3rem 0.85rem; min-height: 0; line-height: 1.3;
}}
.stTabs [data-baseweb="tab-list"] {{ gap: 8px; border-bottom: 1px solid {BORDER}; }}
.stTabs [aria-selected="true"] {{ color: {ACCENT} !important; font-weight: 600; }}
a {{ color: {ACCENT}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
[data-testid="stMetricValue"], .stDataFrame {{ font-variant-numeric: tabular-nums; }}
.nih-header {{ text-align: center; padding: 14px 0 22px 0; margin-bottom: 8px; }}
.nih-header h1 {{ color: {INK} !important; margin: 0; font-size: 2.1rem;
    font-weight: 600; letter-spacing: -0.03em; }}
.nih-header p {{ color: {MUTED}; margin: 7px 0 0 0; font-size: 1.02rem;
    font-weight: 400; }}
.kpi {{
    border: 1px solid {BORDER}; border-radius: 16px; padding: 16px 18px;
    background: #ffffff; height: 100%;
}}
.kpi .num {{ font-weight: 600; font-size: 1.7rem; color: {INK}; line-height: 1.15;
    letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }}
.kpi .lab {{ font-size: 0.72rem; color: {MUTED}; text-transform: uppercase;
    letter-spacing: 0.06em; margin-top: 2px; }}
.kpi .sub {{ font-size: 0.74rem; color: {MUTED}; margin-top: 3px; }}
</style>""", unsafe_allow_html=True)

st.markdown(
    '<div class="nih-header"><h1>NIH RePORTER</h1>'
    '<p>NIH/HHS award intelligence · live from the NIH RePORTER API</p></div>',
    unsafe_allow_html=True)

# Always-available "New query" reset at the very top (prominent).
if st.columns([5, 2])[1].button("＋ New query", type="primary",
                                use_container_width=True,
                                help="Clear everything and start a new question."):
    for _k in ("ask_answer", "ask_engine", "follow_thread", "ask_question",
               "asked_question"):
        st.session_state.pop(_k, None)
    st.rerun()


def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, default)


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime((d or "")[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return d or ""


def kpi(col, label, value, sub=""):
    col.markdown(
        f'<div class="kpi"><div class="num">{value}</div>'
        f'<div class="lab">{label}</div>'
        + (f'<div class="sub">{sub}</div>' if sub else "")
        + "</div>", unsafe_allow_html=True)


def bar(series: dict, title: str, top: int = 12):
    """Horizontal bar chart from a {label: count} dict."""
    if not series:
        st.caption(f"_{title}: no data_")
        return
    s = pd.Series(dict(list(series.items())[:top]), name="Awards")
    s.index.name = title
    st.bar_chart(s, horizontal=True, color=EMORY_BLUE, height=max(140, 28 * len(s)))


# One-click example reports shown front and center (label, question).
EXAMPLE_REPORTS = [
    ("Investigators with 3+ grants",
     "Over the last 4 fiscal years, how many investigators have 3 or more grants "
     "where they are PI, and how many have 4 or more? List them with their grant "
     "counts."),
    ("Executive summary",
     "Write an executive summary of these new NIH awards for research leadership: "
     "funding totals, the most notable awards, key research themes, and the mix of "
     "new vs. renewal awards."),
    ("Largest awards",
     "What are the largest awards in this set? List the top awards with PI, "
     "institute, mechanism, and amount."),
    ("Funding by institute",
     "Break down the awards by NIH Institute/Center: counts and total funding, and "
     "say which areas dominate."),
    ("New vs. renewal",
     "How many awards are new vs. renewal vs. continuation, and what does that mix "
     "suggest about the portfolio?"),
    ("Active grants snapshot",
     "Summarize all currently active grants: how many there are, total active "
     "funding, the leading institutes, and the largest active awards."),
]
DEFAULT_QUESTION = EXAMPLE_REPORTS[0][1]


def build_facts(items: list) -> str:
    """Exact, deterministically computed facts handed to the LLM for answers."""
    a = reporter.aggregate(items)
    dist = reporter.grant_count_distribution(items, thresholds=(1, 2, 3, 4, 5, 6))
    exact: dict = {}
    for c in dist["counts"].values():
        exact[c] = exact.get(c, 0) + 1
    lines = [
        f"Filters: {st.session_state.get('rep_query', '')}.",
        f"Awards in result set: {a['count']}. Total funding: {reporter.fmt_money(a['total_amount'])}. "
        f"Median award: {reporter.fmt_money(a['median_amount'])}. Largest: {reporter.fmt_money(a['max_amount'])}.",
        f"Distinct principal investigators: {len(dist['counts'])}.",
        "Investigators by number of distinct grants where they are listed PI "
        "(each grant counted once, even if it spans multiple fiscal years):",
    ]
    lines += [f"  - at least {t} grant(s) as PI: {n} investigator(s)"
              for t, n in dist["at_least"].items()]
    lines.append("Exact distribution: "
                 + ", ".join(f"{k} grant(s): {exact[k]} PI(s)" for k in sorted(exact)))
    roles = reporter.pi_role_counts(items)
    lines.append("Investigator roles: 'Contact PI' is the lead PI; 'Co-PI/MPI' is an "
                 "additional PI on a multi-PI grant. NIH RePORTER publishes PD/PIs "
                 "only - co-investigators / other personnel are NOT in the data.")
    lines.append("Top investigators by distinct grants (total; contact PI / co-PI): "
                 + "; ".join(f"{n} ({v['total']}; contact {v['contact']}, "
                            f"co-PI {v['copi']})"
                            for n, v in list(roles.items())[:25]))
    sub = sum(1 for it in items if it.get("is_subproject"))
    multi = sum(1 for it in items if it.get("multi_pi"))
    lines.append(f"Grants that are subprojects: {sub}. Multi-PI grants: {multi}.")
    def _counts_line(d, n=20):
        return ", ".join(f"{k}: {v}" for k, v in list(d.items())[:n])

    def _money_line(d, n=20):
        return ", ".join(f"{k}: {reporter.fmt_money(v)}" for k, v in list(d.items())[:n])

    # Counts and funding ($) for every dimension, so any "by X" question works.
    lines.append("Awards (count) by fiscal year: " + _counts_line(a["by_fy"]))
    lines.append("Funding ($) by fiscal year: " + _money_line(a["funding_by_fy"]))
    lines.append("Awards by IC: " + _counts_line(a["by_ic"]))
    lines.append("Funding ($) by IC: " + _money_line(a["funding_by_ic"]))
    lines.append("Awards by activity code: " + _counts_line(a["by_activity"]))
    lines.append("Funding ($) by activity code: " + _money_line(a["funding_by_activity"]))
    lines.append("Awards by application type: " + _counts_line(a["by_app_type"]))
    lines.append("Funding ($) by application type: " + _money_line(a["funding_by_app_type"]))
    if len(a["by_org"]) > 1:
        lines.append("Awards by institution: " + _counts_line(a["by_org"], 15))
        lines.append("Funding ($) by institution: " + _money_line(a["funding_by_org"], 15))
    if len(a["by_state"]) > 1:
        lines.append("Awards by state: " + _counts_line(a["by_state"], 15))
    notable = sorted((it for it in items if it.get("amount")),
                     key=lambda i: int(i["amount"]), reverse=True)[:30]
    if notable:
        lines.append("Notable awards (largest by amount):")
        lines += [f"  - {reporter.fmt_money(it['amount'])} | {it.get('ic', '')} "
                  f"{it.get('activity_code', '')} {it.get('app_type', '')} | "
                  f"PI: {it.get('pi', '')} | {it.get('title', '')}" for it in notable]
    return "\n".join(lines)


def _col(df: pd.DataFrame, name: str):
    return df[name] if name in df.columns else ""


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """Strip control characters openpyxl rejects from all string cells."""
    for c in df.columns:
        df[c] = df[c].map(
            lambda v: _ILLEGAL_XLSX.sub("", v) if isinstance(v, str) else v)
    return df


def build_workbook(items: list, query: str, summary_md: str = "") -> bytes:
    """A complete .xlsx workbook of the result set: every award with all fields,
    plus investigator roles, breakdowns, a summary, and any narrative report. No
    truncation — every grant in the current result set is included."""
    agg = reporter.aggregate(items)
    df = pd.DataFrame(items)
    if "years_in_window" in df.columns:
        fy = df["years_in_window"].apply(
            lambda y: ", ".join(str(v) for v in y) if isinstance(y, list) else y)
    else:
        fy = _col(df, "fiscal_year")
    awards = pd.DataFrame({
        "Award notice date": _col(df, "award_date"),
        "Fiscal year(s)": fy,
        "IC": _col(df, "ic"),
        "Activity code": _col(df, "activity_code"),
        "Application type": _col(df, "app_type"),
        "Amount (window total)": _col(df, "amount"),
        "Contact PI": _col(df, "contact_pi"),
        "All PIs": _col(df, "pi"),
        "Multi-PI": _col(df, "multi_pi"),
        "Subproject": _col(df, "is_subproject"),
        "Organization": _col(df, "org"),
        "City": _col(df, "city"),
        "State": _col(df, "state"),
        "Project number": _col(df, "project_num"),
        "Core project number": _col(df, "core_num"),
        "Project start": _col(df, "start"),
        "Project end": _col(df, "end"),
        "Title": _col(df, "title"),
        "RePORTER URL": _col(df, "url"),
        "Abstract": _col(df, "abstract"),
    })
    roles = reporter.pi_role_counts(items)
    investigators = pd.DataFrame(
        [{"Investigator": n, "Distinct grants (PI)": v["total"],
          "As contact PI": v["contact"], "As co-PI / MPI": v["copi"]}
         for n, v in roles.items()])
    summary = pd.DataFrame({
        "Metric": ["Query", "Awards (distinct grants)", "Total funding",
                   "Median award", "Largest award", "Distinct investigators",
                   "Institutes / Centers"],
        "Value": [query, agg["count"], agg["total_amount"], agg["median_amount"],
                  agg["max_amount"], len(roles), len(agg["by_ic"])]})

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        _clean_df(summary).to_excel(xl, sheet_name="Summary", index=False)
        _clean_df(awards).to_excel(xl, sheet_name="Awards", index=False)
        if not investigators.empty:
            _clean_df(investigators).to_excel(xl, sheet_name="Investigators", index=False)
        for sheet, key in (("By IC", "by_ic"), ("By activity", "by_activity"),
                           ("By application type", "by_app_type"),
                           ("By fiscal year", "by_fy"), ("By organization", "by_org")):
            d = agg.get(key) or {}
            if d:
                _clean_df(pd.DataFrame({"Value": [str(k) for k in d],
                                        "Grants": list(d.values())})
                          ).to_excel(xl, sheet_name=sheet[:31], index=False)
        if summary_md:
            _clean_df(pd.DataFrame({"Report": summary_md.split("\n")})).to_excel(
                xl, sheet_name="Report", index=False)
    return out.getvalue()


_CHART_WORDS = ("chart", "graph", "plot", "bar", "visuali", "trend", "compare",
                "comparison", "breakdown", "distribution", "over time", "by year")
_FUND_WORDS = ("$", "fund", "dollar", "amount", "money", "spend", "budget", "award size")
_COUNT_WORDS = ("number", "count", "how many", "# of", "volume", "tally")
_DIM_KEYS = {
    "fy": (("fiscal year", "by year", "per year", "each year", "over time", "annual",
            "by fy", "per fy", "year by year", "yearly", "trend"),
           "funding_by_fy", "by_fy", "fiscal year"),
    "ic": (("institute", "center", "by ic", " ic "), "funding_by_ic", "by_ic",
           "Institute / Center"),
    "activity": (("activity", "mechanism", "grant type", "by r0", "award type"),
                 "funding_by_activity", "by_activity", "activity code"),
    "app_type": (("application type", "new vs", "renewal", "competing", "new versus"),
                 "funding_by_app_type", "by_app_type", "application type"),
    "org": (("institution", "organization", "university", " org"),
            "funding_by_org", "by_org", "institution"),
    "state": (("state",), "funding_by_state", "by_state", "state"),
}


def maybe_chart(question: str, agg: dict):
    """Render a bar chart when the question asks for one — for whatever dimension
    (fiscal year, IC, activity, application type, org, state) and metric (funding
    $ or award count) it mentions. Generic, so it works across questions."""
    q = (question or "").lower()
    if not any(w in q for w in _CHART_WORDS):
        return
    metric = ("funding" if any(w in q for w in _FUND_WORDS)
              else "count" if any(w in q for w in _COUNT_WORDS) else "funding")
    dim = next((d for d, (kw, *_) in _DIM_KEYS.items() if any(k in q for k in kw)), None)
    if dim is None:
        dim = "fy" if len(agg.get("funding_by_fy") or {}) > 1 else "ic"
    _, fund_key, count_key, dim_label = _DIM_KEYS[dim]
    data = agg.get(fund_key if metric == "funding" else count_key) or {}
    rows = list(data.items())
    if dim != "fy":
        rows = rows[:15]
    if not rows:
        return
    ylabel = "Funding ($)" if metric == "funding" else "Awards"
    s = pd.Series({str(k): v for k, v in rows}, name=ylabel)
    st.markdown(f"**{ylabel} by {dim_label}**")
    st.bar_chart(s, color=EMORY_BLUE, horizontal=(dim != "fy"),
                 height=max(160, 30 * len(s)) if dim != "fy" else 300)


# ============================ Filter state ============================
# Filters are hidden by default; the AI question leads. The actual filter widgets
# render in a collapsed "Manual filter search" panel at the bottom of the page and
# write to these f_* keys. We read the current values here (with defaults) so the
# data fetch below always reflects them.
FY_NOW = datetime.now().year
# NIH fiscal year starts Oct 1, so Oct–Dec belong to the next fiscal year.
CURRENT_FY = FY_NOW + (1 if datetime.now().month >= 10 else 0)
FY_OPTIONS = list(range(FY_NOW, FY_NOW - 6, -1))
STATE_OPTIONS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR"]

# A reset stages a flag, then clears the widget-managed keys here (before any
# widget is instantiated, which Streamlit requires).
if st.session_state.pop("_reset_filters", False):
    for _k in ("f_mode", "f_org", "f_pi", "f_topic", "f_ic", "f_act", "f_states",
               "f_amt", "f_days", "f_fy", "f_newly", "f_active", "f_limit",
               "rep_items", "ask_answer", "rep_summary"):
        st.session_state.pop(_k, None)

mode = st.session_state.get("f_mode", "My institution's new awards")
org_mode = mode.startswith("My institution")
org_name = st.session_state.get("f_org", reporter.DEFAULT_ORG)
pi_name = st.session_state.get("f_pi", "")
topic = st.session_state.get("f_topic", "")
ic_codes = st.session_state.get("f_ic", [])
activity_codes = st.session_state.get("f_act", [])
states = st.session_state.get("f_states", [])
amt = st.session_state.get("f_amt", (0, 5000))
award_min = amt[0] * 1000 if amt[0] > 0 else None
award_max = amt[1] * 1000 if amt[1] < 5000 else None
rep_days = st.session_state.get("f_days", 7)
fiscal_years = st.session_state.get("f_fy", [])
newly_added = st.session_state.get("f_newly", False)
active_only = st.session_state.get("f_active", False)
rep_limit = st.session_state.get("f_limit", 200)


def render_filters():
    """The optional manual filter panel, rendered at the bottom of the page."""
    st.divider()
    with st.expander("Manual filter search (optional)", expanded=False):
        st.caption("Refine what the AI analyzes. Changes update the report "
                   "automatically — no need to re-run.")
        m = st.session_state.get("f_mode", "My institution's new awards")
        inst_mode = m.startswith("My institution")
        c1, c2 = st.columns(2)
        c1.radio("Search mode",
                 ["My institution's new awards", "Topic search (all institutions)"],
                 key="f_mode")
        c2.text_input("Organization", value=reporter.DEFAULT_ORG, key="f_org",
                      disabled=not inst_mode)
        c1.text_input("Principal investigator", key="f_pi",
                      placeholder="e.g. Smith, Jane")
        c2.text_input("Research terms", key="f_topic",
                      placeholder="e.g. gene therapy, Alzheimer's, CRISPR")
        c1.multiselect("Institute / Center (IC)",
                       options=list(reporter.IC_CHOICES.keys()),
                       format_func=lambda c: f"{c} — {reporter.IC_CHOICES[c]}",
                       key="f_ic")
        c2.multiselect("Activity code",
                       options=list(reporter.ACTIVITY_CHOICES.keys()),
                       format_func=lambda c: f"{c} — {reporter.ACTIVITY_CHOICES[c]}",
                       key="f_act")
        c1.multiselect("Organization state(s)", STATE_OPTIONS, key="f_states",
                       disabled=inst_mode)
        c2.multiselect("Fiscal year(s) — up to 5 back", FY_OPTIONS, key="f_fy",
                       help="Select fiscal years for multi-year, investigator-level "
                            "analysis. Overrides the day look-back.")
        c1.slider("Award size ($K)", 0, 5000, (0, 5000), step=50, key="f_amt")
        c2.slider("Or look back (days)", 7, 365, 7, key="f_days",
                  disabled=bool(st.session_state.get("f_fy")))
        c1.checkbox("Newly added to RePORTER only", key="f_newly")
        c2.checkbox("Active grants only (current project period)", key="f_active",
                    help="Restrict to grants whose award period is ongoing today. "
                         "Spans the whole portfolio, ignoring the day look-back.")
        c1.slider("Max awards", 50, 2000, 200, step=50, key="f_limit")
        if st.button("Reset to defaults"):
            st.session_state["_reset_filters"] = True
            st.rerun()
    st.caption("Claude summaries enabled." if summarize.claude_available()
               else "No ANTHROPIC_API_KEY set — using template summaries.")


def run_query():
    # Fiscal-year selection defines the time window and overrides the day look-back.
    return reporter.fetch_awards(
        org_names=[org_name] if (org_mode and org_name.strip()) else None,
        pi_name=pi_name, text_query=topic,
        ic_codes=ic_codes or None, activity_codes=activity_codes or None,
        org_states=states or None, award_min=award_min, award_max=award_max,
        use_award_window=not bool(fiscal_years),
        days_back=rep_days, fiscal_years=fiscal_years or None,
        newly_added_only=newly_added, active_only=active_only,
        limit=2000 if active_only else rep_limit)


def ai_fetch(parsed: dict):
    """Fetch awards using ONLY criteria parsed from the question. The single
    default is the home institution (Emory); every other dimension — time
    window, IC, activity code, state, award size — comes from the question.
    Returns (awards, error, label).
    """
    if parsed.get("all_institutions"):
        o_names = None
    elif parsed.get("organization"):
        o_names = [parsed["organization"]]
    else:
        o_names = [reporter.DEFAULT_ORG]
    fys = parsed.get("fiscal_years") or None
    days = parsed.get("days_back")
    eff_active = bool(parsed.get("active_only"))
    eff_topic = parsed.get("topic") or ""
    eff_pi = parsed.get("pi_name") or ""
    eff_ic = parsed.get("ic_codes") or None
    eff_act = parsed.get("activity_codes") or None
    eff_newly = bool(parsed.get("newly_added"))
    # No window in the question -> no time filter at all (all available data),
    # rather than imposing a default window the user didn't ask for.
    awards, err = reporter.fetch_awards(
        org_names=o_names, pi_name=eff_pi, text_query=eff_topic,
        ic_codes=eff_ic, activity_codes=eff_act, org_states=None,
        award_min=None, award_max=None,
        use_award_window=bool(days),
        days_back=days or 7, fiscal_years=fys, newly_added_only=eff_newly,
        active_only=eff_active, limit=800 if (days and not eff_active) else 2000)
    parts = [o_names[0] if o_names else "All institutions"]
    if eff_pi:
        parts.append(f"PI: {eff_pi}")
    if eff_topic:
        parts.append(f"topic: {eff_topic}")
    if eff_ic:
        parts.append("IC: " + ", ".join(eff_ic))
    if eff_act:
        parts.append("mech: " + ", ".join(eff_act))
    if fys:
        parts.append("FY " + ", ".join(str(y) for y in sorted(fys, reverse=True)))
    elif days:
        parts.append(f"last {days} days")
    if eff_active:
        parts.append("active grants only")
    if not (fys or days or eff_active):
        parts.append("all available (no date filter)")
    return awards, err, " · ".join(parts)


def query_label() -> str:
    filt = [org_name.strip() if (org_mode and org_name.strip()) else "All institutions"]
    for label, val in (("PI", pi_name), ("topic", topic), ("IC", ", ".join(ic_codes)),
                       ("mech", ", ".join(activity_codes)), ("states", ", ".join(states))):
        if val:
            filt.append(f"{label}: {val}")
    # The time window is fiscal years when selected, otherwise the day look-back.
    if fiscal_years:
        filt.append("FY " + ", ".join(str(y) for y in sorted(fiscal_years, reverse=True)))
    else:
        filt.append(f"last {rep_days} days")
    return " · ".join(filt)


def filter_sig():
    return (org_mode, org_name, pi_name, topic, tuple(ic_codes), tuple(activity_codes),
            tuple(states), award_min, award_max, rep_days, tuple(sorted(fiscal_years)),
            newly_added, active_only, rep_limit)


def store_results(awards, rep_err):
    if rep_err:
        awards, used_sample = reporter.sample_awards(), True
    else:
        used_sample = False
    st.session_state.rep_items = awards
    st.session_state.rep_error = rep_err
    st.session_state.rep_sample = used_sample
    st.session_state.rep_query = query_label()
    st.session_state.filter_sig = filter_sig()
    st.session_state.pop("rep_summary", None)
    st.session_state.pop("ask_answer", None)
    st.session_state.pop("follow_thread", None)


# Fetch whenever the filters change (or on first load), so the AI answers and
# reports always reflect the current filters — no stale data, no button needed.
if "rep_items" not in st.session_state or st.session_state.get("filter_sig") != filter_sig():
    with st.spinner("Loading NIH awards..."):
        awards, rep_err = run_query()
    store_results(awards, rep_err)

rep_items = st.session_state.get("rep_items")

if st.session_state.get("rep_sample"):
    st.warning(f"Live NIH RePORTER API unreachable from this environment "
               f"({st.session_state.get('rep_error')}); showing bundled sample "
               "awards so the report still renders. (Benchmarking needs the live API.)")

if not rep_items:
    st.warning("No NIH awards matched these filters. Try a longer look-back, "
               "broader terms, fewer filters, or add a fiscal year.")
    st.stop()

agg = reporter.aggregate(rep_items)


@st.cache_data(show_spinner=False)
def _workbook(sig: str, _items: list, _query: str, _summary_md: str) -> bytes:
    # Leading-underscore args are excluded from the cache key, so `sig` alone
    # determines reuse (avoids hashing the unhashable list of dicts each run).
    return build_workbook(_items, _query, _summary_md)


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Build the workbook only in the report view (where the downloads live), and never
# let a build error take down the app — fall back to no Excel if it fails.
xlsx_data = None
if st.session_state.get("ask_answer"):
    try:
        _xlsx_sig = (f"{st.session_state.get('rep_query', '')}|{len(rep_items)}|"
                     f"{bool(st.session_state.get('rep_summary'))}")
        xlsx_data = _workbook(_xlsx_sig, rep_items, st.session_state.get("rep_query", ""),
                              st.session_state.get("rep_summary", ""))
    except Exception:  # noqa: BLE001 - downloads degrade gracefully
        xlsx_data = None

# ============================ AI report box — the start screen ============================
# Apply a pending example question chosen on the previous run. This must happen
# before the text_area widget is created, or Streamlit rejects the state change.
if "pending_q" in st.session_state:
    st.session_state.ask_question = st.session_state.pop("pending_q")
st.session_state.setdefault("ask_question", "")

if not st.session_state.get("ask_answer"):
    # ----- Start screen: just the search box and (small) example reports -----
    st.write("")
    st.write("")
    _left, _center, _right = st.columns([1, 2.4, 1])
    with _center:
        st.text_area("Your question", key="ask_question", height=110,
                     label_visibility="collapsed",
                     placeholder="Ask anything about NIH funding…")
        ask_clicked = st.button("Generate report", type="primary",
                                use_container_width=True)

    st.write("")
    # Smaller example buttons so the input box stands out.
    ex_cols = st.columns([1] + [2] * len(EXAMPLE_REPORTS) + [1])
    for col, (label, q) in zip(ex_cols[1:-1], EXAMPLE_REPORTS):
        if col.button(label, use_container_width=True, key=f"ex_{label}"):
            st.session_state.pending_q = q
            st.session_state.run_ask = True
            st.rerun()

    if (ask_clicked and st.session_state.ask_question.strip()) \
            or st.session_state.pop("run_ask", False):
        q = st.session_state.ask_question
        # The question drives the data: parse its scope/window, pull that, answer.
        with st.spinner("Reading your request and pulling the matching awards..."):
            parsed, _ = summarize.parse_query(
                q, CURRENT_FY, list(reporter.IC_CHOICES), list(reporter.ACTIVITY_CHOICES))
            awards, err, label = ai_fetch(parsed)
            if err:
                awards = reporter.sample_awards()
                st.session_state.rep_sample = True
            else:
                st.session_state.rep_sample = False
            st.session_state.rep_items = awards
            st.session_state.rep_query = label
            st.session_state.filter_sig = filter_sig()
        with st.spinner("Analyzing the data..."):
            answer, engine = summarize.custom_report(q, build_facts(awards))
        st.session_state.ask_answer = answer
        st.session_state.ask_engine = engine
        st.session_state.asked_question = q   # the original question, preserved
        st.session_state.follow_thread = []   # fresh report -> fresh follow-up thread
        st.rerun()

else:
    # ----- Report view: the top search box is hidden; report + follow-up lead. -----
    st.subheader("Your report")
    st.caption("Question: " + st.session_state.get("asked_question",
                                                   st.session_state.get("ask_question", "")))
    with st.container(border=True):
        st.markdown(st.session_state.ask_answer)
        maybe_chart(st.session_state.get("asked_question",
                                         st.session_state.get("ask_question", "")), agg)
        st.caption("Covering: " + st.session_state.get("rep_query", ""))
        if st.session_state.get("ask_engine") == "claude":
            st.caption(f"Engine: Claude ({summarize.MODEL}) · figures pre-computed")
    dlc1, dlc2 = st.columns(2)
    if xlsx_data:
        dlc1.download_button("Download data (Excel)", xlsx_data,
                             file_name="nih_reporter_data.xlsx", mime=XLSX_MIME,
                             use_container_width=True,
                             help="Every grant in this result set, with all fields, "
                                  "plus investigator roles and breakdowns.")
    dlc2.download_button("Download report (Markdown)", st.session_state.ask_answer,
                         file_name="nih_report.md", mime="text/markdown",
                         use_container_width=True)

    # ---- Follow-up: builds on the original question + the data it produced ----
    st.markdown("### Ask a follow-up about this report")
    st.caption("Builds on the question and the exact data above — same result set, "
               "no new search.")
    # The conversation so far renders first; the input box always sits at the
    # very bottom, directly under the most recent answer.
    for turn in st.session_state.get("follow_thread", []):
        st.markdown(f"**Follow-up:** {turn['q']}")
        with st.container(border=True):
            st.markdown(turn["a"])
            maybe_chart(turn["q"], agg)

    with st.form("followup_form", clear_on_submit=True):
        follow_q = st.text_input(
            "Follow-up question", label_visibility="collapsed",
            placeholder="e.g. Of those, which are at the School of Medicine? "
                        "Break the total down by mechanism.")
        follow_go = st.form_submit_button("Ask follow-up")
    if follow_go and follow_q.strip():
        prior = ["Original question: " + st.session_state.get(
                     "asked_question", st.session_state.get("ask_question", "")),
                 "Original answer: " + st.session_state.get("ask_answer", "")[:1800]]
        for t in st.session_state.get("follow_thread", [])[-4:]:
            prior += ["Follow-up question: " + t["q"], "Answer: " + t["a"][:1200]]
        with st.spinner("Analyzing these results..."):
            f_ans, f_eng = summarize.custom_report(
                follow_q, build_facts(rep_items), prior="\n\n".join(prior))
        st.session_state.setdefault("follow_thread", []).append(
            {"q": follow_q, "a": f_ans, "engine": f_eng})
        st.rerun()

# The data dashboard and manual filters belong to the report view only — the
# start screen stays just the search box and example reports.
if not st.session_state.get("ask_answer"):
    st.stop()

# ============================ Manual filters (optional, at the bottom) ============================
render_filters()
