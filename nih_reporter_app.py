"""NIH RePORTER Weekly Report - standalone Streamlit app.

A professional weekly report of recently issued NIH/HHS awards, pulled live from
the NIH RePORTER API (https://api.reporter.nih.gov/ - free, no key). Search by
institution, PI, research terms, Institute/Center, activity code, state, and
award size; explore breakdowns, leaderboards, and peer benchmarking; then export
or deliver the report by email, Teams, or Slack.

Runs independently of the FedWatch dashboard; both share fedwatch/reporter.py.

Run with:  streamlit run nih_reporter_app.py
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from fedwatch import emailer, notify, reporter, summarize

st.set_page_config(page_title="NIH RePORTER Weekly Report", page_icon="🔬",
                   layout="wide", initial_sidebar_state="collapsed")

# ---------- Brand styling ----------
EMORY_BLUE = "#012169"
EMORY_GOLD = "#f2a900"
EMORY_LIGHT_BLUE = "#007dba"

st.markdown(f"""<style>
h1, h2, h3 {{ color: {EMORY_BLUE} !important; font-family: Georgia, 'Times New Roman', serif; }}
[data-testid="stSidebar"] {{ background: #f7f8fb; border-right: 1px solid #e3e7ee; }}
[data-testid="stSidebar"] h1 {{ color: {EMORY_BLUE} !important; font-size: 1.35rem; }}
[data-testid="stExpander"] {{
    border: 1px solid #e3e7ee; border-radius: 10px; background: #ffffff;
    margin-bottom: 6px; box-shadow: 0 1px 2px rgba(1,33,105,0.04);
}}
.stButton button[kind="primary"], .stDownloadButton button {{
    background-color: {EMORY_BLUE}; color: #ffffff; border: none; border-radius: 6px;
}}
.stButton button[kind="primary"]:hover, .stDownloadButton button:hover {{
    background-color: {EMORY_LIGHT_BLUE}; color: #ffffff;
}}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 2px solid #e3e7ee; }}
.stTabs [aria-selected="true"] {{ color: {EMORY_BLUE} !important; font-weight: 600; }}
a {{ color: {EMORY_LIGHT_BLUE}; }}
.nih-header {{
    background: linear-gradient(135deg, {EMORY_BLUE} 0%, #02297f 100%);
    border-bottom: 4px solid {EMORY_GOLD};
    border-radius: 12px; padding: 18px 26px 14px 26px; margin-bottom: 18px;
}}
.nih-header h1 {{ color: #ffffff !important; margin: 0; font-size: 1.7rem; }}
.nih-header p {{ color: #d6deef; margin: 5px 0 0 0; font-size: 0.9rem; }}
.kpi {{
    border: 1px solid #e3e7ee; border-top: 4px solid {EMORY_BLUE};
    border-radius: 12px; padding: 14px 18px 16px 18px; background: #ffffff;
    box-shadow: 0 1px 3px rgba(1,33,105,0.05); height: 100%;
}}
.kpi .num {{ font: 700 1.8rem Georgia, serif; color: {EMORY_BLUE}; line-height: 1.15; }}
.kpi .lab {{ font-size: 0.72rem; color: #6d6e71; text-transform: uppercase;
    letter-spacing: 0.07em; margin-top: 2px; }}
.kpi .sub {{ font-size: 0.74rem; color: #8a8c8f; margin-top: 3px; }}
</style>""", unsafe_allow_html=True)

st.markdown(
    '<div class="nih-header"><h1>NIH RePORTER Weekly Report</h1>'
    '<p>Recently issued NIH/HHS awards, live from the NIH RePORTER API · '
    'Office of the SVPR</p></div>', unsafe_allow_html=True)


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
    lines.append("Top investigators by grant count: "
                 + "; ".join(f"{n} ({c})" for n, c in dist["counts"].most_common(25)))
    lines.append("Awards by IC: " + ", ".join(f"{k}: {v}" for k, v in a["by_ic"].items()))
    lines.append("Awards by activity code: "
                 + ", ".join(f"{k}: {v}" for k, v in a["by_activity"].items()))
    lines.append("Awards by application type: "
                 + ", ".join(f"{k}: {v}" for k, v in a["by_app_type"].items()))
    if len(a["by_org"]) > 1:
        lines.append("Awards by institution: "
                     + ", ".join(f"{k}: {v}" for k, v in list(a["by_org"].items())[:15]))
    notable = sorted((it for it in items if it.get("amount")),
                     key=lambda i: int(i["amount"]), reverse=True)[:30]
    if notable:
        lines.append("Notable awards (largest by amount):")
        lines += [f"  - {reporter.fmt_money(it['amount'])} | {it.get('ic', '')} "
                  f"{it.get('activity_code', '')} {it.get('app_type', '')} | "
                  f"PI: {it.get('pi', '')} | {it.get('title', '')}" for it in notable]
    return "\n".join(lines)


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
    """Fetch awards using ONLY criteria parsed from the question — the manual
    filter panel is ignored for a top-level AI query, so nothing the user didn't
    ask for is silently applied. Returns (awards, error, label).

    Defaults when the question is silent: organization = the home institution
    (unless it names one or says 'all institutions'); time window = the current
    fiscal year. Everything else (IC, activity code, state, award size) is only
    applied if the question names it.
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
    # No window specified -> default to the current fiscal year (bounded, useful).
    if not fys and not days and not eff_active:
        fys = [CURRENT_FY]
    awards, err = reporter.fetch_awards(
        org_names=o_names, pi_name=eff_pi, text_query=eff_topic,
        ic_codes=eff_ic, activity_codes=eff_act, org_states=None,
        award_min=None, award_max=None,
        use_award_window=not bool(fys),
        days_back=days or 7, fiscal_years=fys, newly_added_only=eff_newly,
        active_only=eff_active, limit=2000 if (fys or eff_active) else 500)
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

# ============================ AI report box — the start screen ============================
# Apply a pending example question chosen on the previous run. This must happen
# before the text_area widget is created, or Streamlit rejects the state change.
if "pending_q" in st.session_state:
    st.session_state.ask_question = st.session_state.pop("pending_q")
st.session_state.setdefault("ask_question", DEFAULT_QUESTION)

st.write("")
st.write("")
# Center the search box in the middle of the screen, like a Google search box.
_left, _center, _right = st.columns([1, 2.4, 1])
with _center:
    st.markdown(
        "<h2 style='text-align:center;margin-bottom:2px;'>Ask for any report on "
        "NIH funding</h2>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align:center;color:#6d6e71;font-size:0.9rem;margin-top:0;'>"
        "Each question searches fresh — it ignores the manual filters and pulls "
        "exactly what you describe (e.g. “active grants only”, “last 4 fiscal "
        f"years”, “NCI R01s”, “all institutions”). Defaults to {reporter.DEFAULT_ORG} "
        "and the current fiscal year unless you say otherwise. Figures are computed "
        "exactly, never invented.</p>",
        unsafe_allow_html=True)
    st.text_area("Your question", key="ask_question", height=90,
                 label_visibility="collapsed",
                 placeholder="e.g. How many investigators hold 3+ active grants as PI?")
    ask_clicked = st.button("Generate report", type="primary", use_container_width=True)

st.write("")
st.markdown("<p style='text-align:center;font-weight:600;margin-bottom:4px;'>"
            "Instant reports</p>", unsafe_allow_html=True)
ex_cols = st.columns(len(EXAMPLE_REPORTS))
for col, (label, q) in zip(ex_cols, EXAMPLE_REPORTS):
    if col.button(label, use_container_width=True, key=f"ex_{label}"):
        st.session_state.pending_q = q
        st.session_state.run_ask = True
        st.rerun()

if ask_clicked or st.session_state.pop("run_ask", False):
    q = st.session_state.ask_question
    # The question drives the data: parse its scope/window, pull that, then answer.
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
        st.session_state.filter_sig = filter_sig()  # don't let auto-refresh overwrite
    with st.spinner("Analyzing the data..."):
        answer, engine = summarize.custom_report(q, build_facts(awards))
    st.session_state.ask_answer = answer
    st.session_state.ask_engine = engine
    st.session_state.follow_thread = []  # fresh report -> fresh follow-up thread
    st.rerun()  # redraw KPIs/charts/data below to match the question's window

if st.session_state.get("ask_answer"):
    with st.container(border=True):
        st.markdown(st.session_state.ask_answer)
        st.caption("Covering: " + st.session_state.get("rep_query", ""))
        if st.session_state.get("ask_engine") == "claude":
            st.caption(f"Engine: Claude ({summarize.MODEL}) · figures pre-computed")
            st.download_button("Download answer (Markdown)",
                               st.session_state.ask_answer,
                               file_name="nih_custom_report.md", mime="text/markdown")

    # ---- Follow-up: keep querying THIS result set (no new fetch) ----
    st.markdown("**Dig deeper into these results**")
    st.caption("Ask follow-up questions about the data above — no new search, same "
               "result set.")
    with st.form("followup_form", clear_on_submit=True):
        follow_q = st.text_input(
            "Follow-up question", label_visibility="collapsed",
            placeholder="e.g. Of those, which are at the School of Medicine? "
                        "Break the total down by mechanism.")
        follow_go = st.form_submit_button("Ask follow-up")
    if follow_go and follow_q.strip():
        prior = []
        prior.append("Q: " + st.session_state.get("ask_question", "")
                     + "\nA: " + st.session_state.get("ask_answer", "")[:1500])
        for t in st.session_state.get("follow_thread", [])[-3:]:
            prior.append("Q: " + t["q"] + "\nA: " + t["a"][:1500])
        with st.spinner("Analyzing these results..."):
            f_ans, f_eng = summarize.custom_report(
                follow_q, build_facts(rep_items), prior="\n\n".join(prior))
        st.session_state.setdefault("follow_thread", []).append(
            {"q": follow_q, "a": f_ans, "engine": f_eng})
        st.rerun()

    for turn in st.session_state.get("follow_thread", []):
        st.markdown(f"**You asked:** {turn['q']}")
        with st.container(border=True):
            st.markdown(turn["a"])

# Exact investigator grant-count numbers backing the flagship example.
_dist = reporter.grant_count_distribution(rep_items, thresholds=(2, 3, 4, 5))
with st.expander("Key numbers — investigators by grants held as PI"):
    kq = st.columns(5)
    kpi(kq[0], "Distinct PIs", str(len(reporter.pi_award_counts(rep_items))))
    for col, t in zip(kq[1:], (2, 3, 4, 5)):
        kpi(col, f"≥ {t} grants", str(_dist["at_least"][t]))
    _multi = [{"Investigator": n, "Grants as PI": c}
              for n, c in reporter.pi_award_counts(rep_items).most_common() if c >= 2]
    if _multi:
        st.dataframe(pd.DataFrame(_multi), hide_index=True, use_container_width=True)
    else:
        st.caption("No investigator holds more than one grant in this result set — "
                   "widen the window or select more fiscal years.")

st.divider()

# ============================ The data ============================
st.subheader("Explore the data")
st.caption("Showing: " + st.session_state.get("rep_query", ""))
k1, k2, k3, k4, k5 = st.columns(5)
kpi(k1, "Awards", f"{agg['count']:,}")
kpi(k2, "Total funding", reporter.fmt_money(agg["total_amount"]))
kpi(k3, "Median award", reporter.fmt_money(agg["median_amount"]))
kpi(k4, "Largest award", reporter.fmt_money(agg["max_amount"]))
kpi(k5, "Institutes", str(len(agg["by_ic"])),
    sub=" · ".join(list(agg["by_ic"])[:3]))
st.write("")

tab_overview, tab_awards, tab_board, tab_bench, tab_report = st.tabs(
    ["Overview", "Awards", "Leaderboards", "Benchmark", "Report"])

# ============================ Overview ============================
with tab_overview:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("By Institute / Center")
        bar(agg["by_ic"], "IC")
        st.subheader("By application type")
        bar(agg["by_app_type"], "Type")
    with c2:
        st.subheader("By activity code")
        bar(agg["by_activity"], "Mechanism")
        if not org_mode and len(agg["by_org"]) > 1:
            st.subheader("By institution")
            bar(agg["by_org"], "Organization")
        else:
            st.subheader("By fiscal year")
            bar({str(k): v for k, v in agg["by_fy"].items()}, "FY")

# ============================ Awards table ============================
with tab_awards:
    df = pd.DataFrame(rep_items)
    show = df[["award_date", "ic", "activity_code", "app_type", "amount",
               "pi", "org", "project_num", "title", "url"]].copy()
    show.columns = ["Award notice", "IC", "Activity", "Type", "Amount",
                    "PI", "Organization", "Project #", "Title", "Link"]
    st.dataframe(
        show, hide_index=True, use_container_width=True, height=460,
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("RePORTER", display_text="Open ↗"),
            "Title": st.column_config.TextColumn(width="large"),
        })
    st.download_button(
        "Export awards (CSV)",
        df[["award_date", "ic", "activity_code", "app_type", "amount", "pi",
            "org", "state", "project_num", "fiscal_year", "title", "url"]]
        .to_csv(index=False),
        file_name="nih_reporter_awards.csv", mime="text/csv")

    with st.expander(f"Award detail cards ({len(rep_items)})"):
        for it in rep_items:
            st.markdown(f"**{it.get('title', '')}**")
            meta = [b for b in (
                it.get("pi") and f"PI: {it['pi']}", it.get("org"),
                it.get("ic"), it.get("activity_code"), it.get("app_type"),
                it.get("project_num"),
                it.get("fiscal_year") and f"FY{it['fiscal_year']}") if b]
            st.caption(" · ".join(meta))
            period = f"{it.get('start') or '?'} – {it.get('end') or '?'}"
            st.markdown(f"**{reporter.fmt_money(it.get('amount'))}** · {period}"
                        + (f" · Award notice {it['award_date']}" if it.get("award_date") else ""))
            if it.get("abstract"):
                st.write(it["abstract"][:900] + ("…" if len(it["abstract"]) > 900 else ""))
            if it.get("url"):
                st.markdown(f"[Open in NIH RePORTER ↗]({it['url']})")
            st.divider()

# ============================ Leaderboards ============================
with tab_board:
    st.caption("Ranked by total award dollars in the current result set.")
    lc1, lc2 = st.columns(2)

    def board(col, key, label):
        rows = reporter.leaderboard(rep_items, key, n=10)
        if not rows or rows[0]["name"] == "—":
            col.caption(f"_No {label.lower()} data._")
            return
        bdf = pd.DataFrame(rows)[["name", "awards", "total_amount"]]
        bdf.columns = [label, "Awards", "Total $"]
        maxv = max(r["total_amount"] for r in rows) or 1
        col.markdown(f"**Top {label.lower()} by funding**")
        col.dataframe(
            bdf, hide_index=True, use_container_width=True,
            column_config={
                "Total $": st.column_config.ProgressColumn(
                    format="$%d", min_value=0, max_value=maxv),
                label: st.column_config.TextColumn(width="medium"),
            })

    board(lc1, "pi", "Principal investigator")
    board(lc2, "org" if not org_mode else "ic",
          "Institution" if not org_mode else "Institute / Center")
    board(lc1, "activity_code", "Activity code")
    board(lc2, "state" if not org_mode else "app_type",
          "State" if not org_mode else "Application type")

# ============================ Benchmark ============================
with tab_bench:
    st.subheader("Peer-institution benchmarking")
    st.caption("Compare award counts and total funding across institutions for "
               "the same time window and topic filters. Requires the live API.")
    default_peers = ("EMORY UNIVERSITY, DUKE UNIVERSITY, VANDERBILT UNIVERSITY, "
                     "WASHINGTON UNIVERSITY, JOHNS HOPKINS UNIVERSITY, "
                     "UNIVERSITY OF PITTSBURGH")
    peers_raw = st.text_area("Institutions (one per line or comma-separated)",
                             value=default_peers, height=90)
    peers = [p.strip() for p in peers_raw.replace("\n", ",").split(",") if p.strip()]
    if st.button("Compare institutions", type="primary"):
        with st.spinner(f"Querying RePORTER for {len(peers)} institutions..."):
            rows, errs = reporter.compare_orgs(
                peers, text_query=topic, ic_codes=ic_codes or None,
                days_back=rep_days, fiscal_years=fiscal_years or None)
        st.session_state.bench_rows = rows
        st.session_state.bench_errs = errs

    if st.session_state.get("bench_errs"):
        st.warning("Some institutions could not be fetched (the live API may be "
                   "unreachable here): " + "; ".join(st.session_state.bench_errs[:3]))
    bench_rows = st.session_state.get("bench_rows")
    if bench_rows:
        bdf = pd.DataFrame(bench_rows)[["org", "awards", "total_amount", "median_amount"]]
        bdf.columns = ["Institution", "Awards", "Total $", "Median $"]
        st.dataframe(bdf, hide_index=True, use_container_width=True,
                     column_config={
                         "Total $": st.column_config.NumberColumn(format="$%d"),
                         "Median $": st.column_config.NumberColumn(format="$%d")})
        chart = pd.Series({r["org"]: r["total_amount"] for r in bench_rows},
                          name="Total $")
        st.bar_chart(chart, horizontal=True, color=EMORY_GOLD)

# ============================ Report / delivery ============================
with tab_report:
    st.subheader("Narrative summary & delivery")
    if st.button("Generate summary", type="primary"):
        with st.spinner("Writing the weekly award summary..."):
            text, engine = summarize.generate_summary(
                rep_items, style="Executive summary",
                extra_instructions=(
                    "These are newly issued NIH research awards, not policy items. "
                    "Lead with funding totals and notable awards (largest dollar "
                    "amounts, prominent institutes), group by research theme, name "
                    "PIs and institutes, and note the mix of new vs. renewal awards. "
                    "Do not invent figures."))
        st.session_state.rep_summary = text
        st.session_state.rep_summary_engine = engine

    if st.session_state.get("rep_summary"):
        st.markdown(st.session_state.rep_summary)
        st.caption("Engine: " + ("Claude (" + summarize.MODEL + ")"
                   if st.session_state.get("rep_summary_engine") == "claude" else "template"))
        rep_title = "NIH RePORTER Weekly Award Report - " + datetime.now().strftime("%b %d, %Y")

        d1, d2, d3 = st.columns(3)
        d1.download_button("Summary (Markdown)", st.session_state.rep_summary,
                           file_name="nih_reporter_summary.md", mime="text/markdown")
        d2.download_button("HTML digest",
                           emailer.build_html(rep_items, st.session_state.rep_summary, rep_title),
                           file_name="nih_reporter_digest.html", mime="text/html")
        d3.download_button("Email (.eml)",
                           emailer.build_eml(rep_items, st.session_state.rep_summary, rep_title),
                           file_name="nih_reporter_digest.eml", mime="message/rfc822")

        st.divider()
        st.markdown("**Post to a channel**")
        teams_hook = _secret("TEAMS_WEBHOOK_URL")
        slack_hook = _secret("SLACK_WEBHOOK_URL")
        p1, p2 = st.columns(2)
        if p1.button("Post to Teams", disabled=not teams_hook,
                     help="Set TEAMS_WEBHOOK_URL in secrets to enable."):
            try:
                notify.send_teams_summary(teams_hook, st.session_state.rep_summary, title=rep_title)
                st.success("Posted to Teams.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Teams post failed: {exc}")
        if p2.button("Post to Slack", disabled=not slack_hook,
                     help="Set SLACK_WEBHOOK_URL in secrets to enable."):
            try:
                notify.send_slack(slack_hook, st.session_state.rep_summary, title=rep_title)
                st.success("Posted to Slack.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Slack post failed: {exc}")
        if not teams_hook and not slack_hook:
            st.caption("Add `TEAMS_WEBHOOK_URL` and/or `SLACK_WEBHOOK_URL` to "
                       "Streamlit secrets to enable channel posting.")
    else:
        st.info("Generate a summary to enable downloads and channel posting.")


# ============================ Manual filters (optional, at the bottom) ============================
render_filters()
