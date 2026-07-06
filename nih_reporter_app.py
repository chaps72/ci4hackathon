"""NIH RePORTER Weekly Report - standalone Streamlit app.

A professional weekly report of recently issued NIH/HHS awards, pulled live from
the NIH RePORTER API (https://api.reporter.nih.gov/ - free, no key). Search by
institution, PI, research terms, Institute/Center, activity code, state, and
award size; explore breakdowns, leaderboards, and peer benchmarking; then export
or deliver the report by email, Teams, or Slack.

Runs independently of the FedWatch dashboard; both share fedwatch/reporter.py.

Run with:  streamlit run nih_reporter_app.py
"""

import base64
import io
import os
import random
import re
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

# Control characters openpyxl rejects in cells (NIH abstracts/titles sometimes
# contain them); strip before writing Excel.
_ILLEGAL_XLSX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

from fedwatch import notify, reporter, summarize

st.set_page_config(page_title="NIH RePORTER Weekly Report", page_icon="🔬",
                   layout="wide", initial_sidebar_state="collapsed")

# ---------- Apple-inspired styling (system font, airy, ghost buttons) ----------
ACCENT = "#012169"        # Emory navy (links, tabs, charts) — professional, not bright
INK = "#1d1d1f"           # Apple near-black text
MUTED = "#6e6e73"         # Apple secondary text
BORDER = "#d2d2d7"        # Apple hairline
PANEL = "#f5f5f7"         # Apple light gray
EMORY_BLUE = ACCENT       # chart series color
# Emory Research brand accents — a light touch over the clean base.
EMORY_NAVY = "#012169"
EMORY_BRAND_GOLD = "#f2a900"

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
    background: {ACCENT}; color: #ffffff; border-color: {ACCENT};
}}
.stFormSubmitButton button {{
    background: #ffffff; color: {INK}; border: 1px solid {BORDER};
    border-radius: 980px; font-weight: 500;
}}
/* Example chips: smaller ghost pills */
.stButton button[kind="secondary"] {{
    font-size: 0.78rem; padding: 0.3rem 0.85rem; min-height: 0; line-height: 1.3;
}}
/* New query / briefing buttons: soft pastel-Emory fill (targeted by widget keys) */
.st-key-newq_top button, .st-key-newq_bottom button, .st-key-newq_exec button,
.st-key-exec_btn button {{
    background: #e7ecf7 !important; color: {EMORY_NAVY} !important;
    border: 1px solid #d4ddf0 !important;
}}
.st-key-newq_top button:hover, .st-key-newq_bottom button:hover,
.st-key-newq_exec button:hover, .st-key-exec_btn button:hover {{
    background: #d8e2f4 !important; color: {EMORY_NAVY} !important;
    border-color: #bcc9ea !important;
}}
.stTabs [data-baseweb="tab-list"] {{ gap: 8px; border-bottom: 1px solid {BORDER}; }}
.stTabs [aria-selected="true"] {{ color: {ACCENT} !important; font-weight: 600; }}
a {{ color: {ACCENT}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.stDataFrame {{ font-variant-numeric: tabular-nums; }}
/* Research-flavored progress: subtle pulse on status/spinner labels */
[data-testid="stStatusWidget"], .stSpinner > div {{ color: {MUTED}; }}
@keyframes nih-pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.55; }} }}
.stSpinner p, [data-testid="stExpanderDetails"] .stMarkdown p em {{
    animation: nih-pulse 1.6s ease-in-out infinite; }}
/* Streamlit's top-right running-man icon -> a researchy microscope */
[data-testid="stStatusWidget"] img, [data-testid="stStatusWidget"] svg {{
    display: none !important; }}
[data-testid="stStatusWidget"]::before {{
    content: "🔬"; display: inline-block; margin-right: 6px;
    animation: nih-pulse 1.2s ease-in-out infinite; }}
/* Tame oversized headings the model may emit inside answers */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{ font-size: 1.1rem !important;
    font-weight: 600 !important; margin: 0.6rem 0 0.25rem !important;
    letter-spacing: -0.01em; }}
.nih-header {{ text-align: center; padding: 14px 0 18px 0; margin-bottom: 8px;
    border-bottom: 2px solid {EMORY_BRAND_GOLD}; }}
.nih-eyebrow {{ color: {EMORY_NAVY}; font-size: 0.72rem; font-weight: 700;
    letter-spacing: 0.16em; text-transform: uppercase; }}
.emory-wordmark {{ display: inline-flex; align-items: center; gap: 14px;
    margin-bottom: 4px; }}
.emory-wordmark .em {{ font-family: Georgia, 'Times New Roman', serif;
    font-weight: 700; font-size: 1.75rem; color: {EMORY_NAVY};
    letter-spacing: 0.01em; line-height: 1; }}
.emory-wordmark .bar {{ width: 1px; height: 1.5rem; background: {EMORY_NAVY};
    opacity: 0.55; }}
.emory-wordmark .res {{ font-family: Georgia, 'Times New Roman', serif;
    font-weight: 400; font-size: 1.0rem; color: {EMORY_NAVY};
    letter-spacing: 0.3em; }}
.nih-header h1 {{ color: {INK} !important; margin: 4px 0 0 0; font-size: 3.1rem;
    font-weight: 700; letter-spacing: -0.035em; }}
.nih-header p {{ color: {MUTED}; margin: 8px 0 0 0; font-size: 1.05rem;
    font-weight: 400; }}
.nih-header p.build {{ color: #b6b6bb; font-size: 0.66rem; margin-top: 5px;
    letter-spacing: 0.04em; }}
</style>""", unsafe_allow_html=True)

def _emory_brand() -> str:
    """Show the Emory Research logo if one is committed at assets/emory_research_logo.*,
    otherwise a navy text wordmark."""
    for ext in ("svg", "png", "jpg", "jpeg"):
        path = os.path.join("assets", f"emory_research_logo.{ext}")
        if os.path.exists(path):
            mime = "svg+xml" if ext == "svg" else ext.replace("jpg", "jpeg")
            b64 = base64.b64encode(open(path, "rb").read()).decode()
            return (f'<img src="data:image/{mime};base64,{b64}" '
                    'style="height:34px;margin-bottom:6px;" alt="Emory Research"/>')
    return ('<div class="emory-wordmark"><span class="em">EMORY</span>'
            '<span class="bar"></span><span class="res">RESEARCH</span></div>')


@st.cache_resource(show_spinner=False)
def _build_stamp() -> str:
    """The deployed code's commit (short SHA + date) — shown in the header so
    it's always visible whether the site is running the latest version."""
    try:
        import subprocess
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h · %ad", "--date=format:%b %d, %Y"],
            capture_output=True, text=True, timeout=3,
            cwd=os.path.dirname(os.path.abspath(__file__)))
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - stamp is best-effort
        return ""


_stamp = _build_stamp()
st.markdown(
    f'<div class="nih-header">{_emory_brand()}'
    '<h1>NIH RePORTER</h1>'
    '<p>NIH/HHS award intelligence · live from the NIH RePORTER API</p>'
    + (f'<p class="build">build {_stamp}</p>' if _stamp else "")
    + '</div>',
    unsafe_allow_html=True)

_RESET_KEYS = ("ask_answer", "ask_engine", "follow_thread", "ask_question",
               "asked_question", "clarify_q", "clarify_for", "clarify_reading",
               "clarify_conf", "report_reading", "skip_clarify",
               "suggestions", "report_pdf", "benchmark", "exec_brief")


def reset_query():
    for _k in _RESET_KEYS:
        st.session_state.pop(_k, None)
    st.session_state.pop("_q_consumed", None)
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass
    st.rerun()


# Always-available "New query" reset at the very top (prominent).
if st.columns([5, 2])[1].button("＋ New query", type="primary",
                                use_container_width=True, key="newq_top",
                                help="Clear everything and start a new question."):
    reset_query()


def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, default)


def _password_gate():
    """If APP_PASSWORD is set (secret/env), require it before showing the app."""
    pw = _secret("APP_PASSWORD")
    if not pw or st.session_state.get("authed"):
        return
    _l, _c, _r = st.columns([1, 1.4, 1])
    with _c:
        st.markdown("#### Restricted — enter the access password")
        entered = st.text_input("Password", type="password",
                                label_visibility="collapsed")
        if st.button("Enter", type="primary", use_container_width=True):
            if entered == pw:
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()


_password_gate()


def ai_md(text: str):
    """Render model output, escaping '$' so Streamlit doesn't turn dollar
    amounts (text between two $) into LaTeX math / serif italics."""
    st.markdown((text or "").replace("$", "\\$"))


# ---------- Research-flavored progress (loading/thinking states) ----------
# Each stage has a few rotating phrasings so the wait reads like a research
# assistant at work, not a generic spinner.
_STAGE_MSGS = {
    "parse": ["📖 Reading the research question…",
              "🔍 Framing the query — scope, window, and grain…",
              "📋 Translating your question into a search protocol…"],
    "fetch": ["📡 Querying NIH RePORTER (api.reporter.nih.gov)…",
              "🗄️ Pulling award notices from the NIH archives…",
              "📚 Retrieving grant records…"],
    "crunch": ["🧮 Cross-tabulating awards by institute, mechanism, and year…",
               "🔬 Running the numbers — totals, medians, distributions…",
               "🧪 Aggregating the result set…"],
    "write": ["✍️ Drafting your briefing…",
              "📝 Synthesizing the findings…",
              "🖋️ Writing up the analysis…"],
    "clarify": ["🔎 Reading your question closely…",
                "🤔 Checking the question is fully specified…"],
    "bench": ["🏛️ Pulling peer institution portfolios…",
              "⚖️ Assembling the peer comparison…"],
}


def _stage(kind: str) -> str:
    return random.choice(_STAGE_MSGS[kind])


# One-click example reports shown front and center (label, question).
EXAMPLE_REPORTS = [
    ("What's new this week",
     "What new NIH awards did Emory receive in the last 7 days? Summarize the count "
     "and total funding, list them with PI, institute and amount, and show a chart "
     "of funding by institute."),
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
    ("Peer benchmark",
     "How does Emory's NIH funding this fiscal year compare to peer institutions "
     "like Duke, Vanderbilt, and Johns Hopkins? Show a comparison chart."),
    ("Renewal pipeline",
     "Which currently active Emory grants end within the next 12 months? How many "
     "dollars are at stake, which are the largest, and which institutes are most "
     "exposed?"),
    ("Active grants snapshot",
     "Summarize all currently active grants: how many there are, total active "
     "funding, the leading institutes, and the largest active awards."),
]
DEFAULT_QUESTION = EXAMPLE_REPORTS[0][1]


_PUB_WORDS = ("publication", "publications", "papers", "paper", "pubmed", "output",
              "outputs", "productivity", "published", "citations", "research output")
_ABSTRACT_WORDS = ("abstract", "about", "research area", "research areas", "topic",
                   "theme", "studying", "study focus", "focus on", "subject",
                   "what are these", "what is this", "describe", "research themes",
                   "what kind of research", "areas of research", "science of",
                   "what they study", "research focus", "summarize the research")


def build_facts(items: list, question: str = "") -> str:
    """Exact, deterministically computed facts handed to the LLM for answers."""
    a = reporter.aggregate(items)
    dist = reporter.grant_count_distribution(items, thresholds=(1, 2, 3, 4, 5, 6))
    exact: dict = {}
    for c in dist["counts"].values():
        exact[c] = exact.get(c, 0) + 1
    lines = [
        f"Filters: {st.session_state.get('rep_query', '')}.",
        "NIH RePORTER project data is available from FY1985 onward (no earlier years exist).",
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
    # Renewal pipeline: projects whose current project period ends within a year
    # (supports "what's expiring / renewal risk" questions).
    today = datetime.now().date()
    ending = []
    for it in items:
        try:
            end = datetime.strptime((it.get("end") or "")[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if today <= end <= today + timedelta(days=365):
            ending.append((end, it))
    if ending:
        ending.sort(key=lambda p: p[0])
        tot = sum(int(it.get("amount") or 0) for _, it in ending)
        lines.append(
            f"Renewal pipeline: {len(ending)} project(s) end within the next 12 "
            f"months ({reporter.fmt_money(tot)} of window funding at stake). "
            "Ending soonest: " + "; ".join(
                f"{e:%b %Y} — PI {it.get('contact_pi') or it.get('pi', '')} "
                f"({it.get('ic', '')}, {reporter.fmt_money(it.get('amount'))})"
                for e, it in ending[:8]))
    # Funding concentration (pre-computed shares, so the model never does math).
    if a["total_amount"]:
        pf: dict = {}
        for it in items:
            p = (it.get("contact_pi") or it.get("pi") or "").strip()
            if p:
                pf[p] = pf.get(p, 0) + int(it.get("amount") or 0)
        if pf:
            top5 = sum(sorted(pf.values(), reverse=True)[:5])
            lines.append(f"Concentration: the top 5 contact PIs hold "
                         f"{reporter.fmt_money(top5)} = "
                         f"{100 * top5 / a['total_amount']:.0f}% of total funding.")
        if a["funding_by_ic"]:
            ic0, v0 = next(iter(a["funding_by_ic"].items()))
            lines.append(f"The single largest IC ({ic0}) accounts for "
                         f"{100 * v0 / a['total_amount']:.0f}% of total funding.")
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
    # Year-over-year cross-tab: funding by IC for each fiscal year, so per-
    # institute comparisons across years are answerable.
    fys = sorted(a["funding_by_fy"])
    if len(fys) > 1:
        xt = reporter.funding_crosstab(items, "ic")
        top_ics = list(a["funding_by_ic"])[:12]
        lines.append("Funding ($) by IC per fiscal year (top ICs): " + "; ".join(
            f"{ic} [" + ", ".join(f"FY{fy} {reporter.fmt_money(xt.get(ic, {}).get(fy, 0))}"
                                  for fy in fys) + "]" for ic in top_ics))
    # Weekly / monthly breakdown of new awards (by award-notice date), so
    # 'on a weekly basis' style questions are answerable.
    wk = reporter.by_period(items, "week", "count")
    if 1 < len(wk) <= 30:
        wk_f = reporter.by_period(items, "week", "funding")
        lines.append("New awards by week (week starting; count, funding): "
                     + "; ".join(f"{k}: {v}, {reporter.fmt_money(wk_f.get(k, 0))}"
                                 for k, v in wk.items()))
    mo = reporter.by_period(items, "month", "count")
    if len(mo) > 1:
        mo_f = reporter.by_period(items, "month", "funding")
        lines.append("New awards by month (count, funding): "
                     + "; ".join(f"{k}: {v}, {reporter.fmt_money(mo_f.get(k, 0))}"
                                 for k, v in mo.items()))
    notable = sorted((it for it in items if it.get("amount")),
                     key=lambda i: int(i["amount"]), reverse=True)[:30]
    if notable:
        lines.append("Notable awards (largest by amount):")
        lines += [f"  - {reporter.fmt_money(it['amount'])} | {it.get('ic', '')} "
                  f"{it.get('activity_code', '')} {it.get('app_type', '')} | "
                  f"PI: {it.get('pi', '')} | {it.get('title', '')}" for it in notable]
    # Abstracts are already fetched (free from RePORTER); include a capped sample
    # ONLY when the question is about research content, to keep token cost low.
    if question and any(w in question.lower() for w in _ABSTRACT_WORDS):
        with_abs = [it for it in notable if it.get("abstract")][:15]
        if with_abs:
            lines.append("Abstracts for the top awards (for research-theme questions):")
            lines += [f"  - {it.get('title', '')} (PI {it.get('pi', '')}, "
                      f"{it.get('ic', '')}): {it['abstract'][:600]}" for it in with_abs]
    # Linked publications (research output) — fetched only when the question is
    # about outputs, to keep it cheap. Patents and clinical-trial links are not
    # reliably exposed by RePORTER's public API, so we note that.
    if question and any(w in question.lower() for w in _PUB_WORDS):
        cores = [it.get("core_num") for it in items if it.get("core_num")]
        pubs, perr = reporter.publication_counts(cores)
        if perr and not pubs:
            lines.append("Publications: linkage could not be retrieved right now "
                         f"({perr}).")
        else:
            total_pubs = sum(pubs.values())
            covered = sum(1 for c in set(cores) if pubs.get((c or '').upper()))
            lines.append(f"Linked publications (NIH RePORTER / PubMed): {total_pubs} "
                         f"publications linked across {covered} grants in this set "
                         "(grants without linked pubs have 0).")
            by_pi = {}
            for it in items:
                n = pubs.get((it.get("core_num") or "").upper(), 0)
                if n:
                    by_pi.setdefault(it.get("title", "")[:60] + f" (PI {it.get('pi','')})", 0)
                    by_pi[it.get("title", "")[:60] + f" (PI {it.get('pi','')})"] += n
            top = sorted(by_pi.items(), key=lambda kv: kv[1], reverse=True)[:12]
            if top:
                lines.append("Most-publishing grants (title (PI): #pubs): "
                             + "; ".join(f"{k}: {v}" for k, v in top))
        lines.append("Note: NIH RePORTER's public API links PUBLICATIONS only; "
                     "patents and clinical-trial links are not reliably available "
                     "from it.")
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
        from openpyxl.chart import BarChart, Reference
        fund_keys = {"by_ic": "funding_by_ic", "by_activity": "funding_by_activity",
                     "by_app_type": "funding_by_app_type", "by_fy": "funding_by_fy",
                     "by_org": "funding_by_org"}
        for sheet, key in (("By IC", "by_ic"), ("By activity", "by_activity"),
                           ("By application type", "by_app_type"),
                           ("By fiscal year", "by_fy"), ("By organization", "by_org")):
            d = agg.get(key) or {}
            if not d:
                continue
            fd = agg.get(fund_keys[key]) or {}
            sn = sheet[:31]
            _clean_df(pd.DataFrame({"Value": [str(k) for k in d],
                                    "Grants": list(d.values()),
                                    "Funding ($)": [fd.get(k, 0) for k in d]})
                      ).to_excel(xl, sheet_name=sn, index=False)
            # Native bar chart of funding by category, on the same sheet.
            ws = xl.book[sn]
            n = len(d)
            chart = BarChart()
            chart.type = "bar"
            chart.title = sheet
            chart.legend = None
            chart.add_data(Reference(ws, min_col=3, min_row=1, max_row=n + 1),
                           titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + 1))
            chart.height, chart.width = max(6, min(22, n * 0.55)), 16
            ws.add_chart(chart, "E2")
        if summary_md:
            _clean_df(pd.DataFrame({"Report": summary_md.split("\n")})).to_excel(
                xl, sheet_name="Report", index=False)
    return out.getvalue()


def _money_fmt(x, _pos=None):
    return f"${x/1e6:.1f}M" if x >= 1e6 else (f"${x/1e3:.0f}K" if x >= 1e3 else f"${x:.0f}")


def build_pdf(items: list, agg: dict, query: str, answer: str, scope: dict) -> bytes:
    """A multi-page PDF: a title + narrative page, then several bar charts."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.ticker import FuncFormatter

    navy, ink, muted = "#012169", "#1d1d1f", "#6e6e73"
    scope = scope or {}
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # --- Title + narrative page ---
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.08, 0.955, "EMORY RESEARCH", color=navy, fontsize=11, fontweight="bold")
        fig.text(0.08, 0.93, "NIH RePORTER report", color=ink, fontsize=22, fontweight="bold")
        fig.text(0.08, 0.905, f"Covering: {query}", color=muted, fontsize=9)
        fig.text(0.08, 0.892, datetime.now().strftime("Generated %B %d, %Y"),
                 color=muted, fontsize=8)
        body = re.sub(r"[*#`>]", "", answer or "")
        lines = []
        for para in body.split("\n"):
            lines += (textwrap.wrap(para, width=98) or [""])
        fig.text(0.08, 0.86, "\n".join(lines[:78]), color=ink, fontsize=9.5, va="top")
        plt.axis("off")
        pdf.savefig(fig)
        plt.close(fig)

        def bar_page(title, d, vertical=False, money=True, top=12, line=False):
            if not d:
                return
            rows = list(d.items()) if line else list(d.items())[:top]
            labels = [str(k) for k, _ in rows]
            vals = [v for _, v in rows]
            fig, ax = plt.subplots(figsize=(8.5, 5.6))
            if line:
                # A long time series reads as a trend line, not a wall of bars.
                ax.plot(labels, vals, color=navy, linewidth=2, marker="o",
                        markersize=4)
                ax.tick_params(axis="x", rotation=45)
                if money:
                    ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
            elif vertical:
                ax.bar(labels, vals, color=navy)
                ax.tick_params(axis="x", rotation=45)
                if money:
                    ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
            else:
                ax.barh(labels[::-1], vals[::-1], color=navy)
                if money:
                    ax.xaxis.set_major_formatter(FuncFormatter(_money_fmt))
            ax.set_title(title, color=navy, fontsize=14, fontweight="bold", loc="left", pad=14)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            ax.tick_params(colors=ink, labelsize=9)
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        if len(agg.get("funding_by_fy") or {}) > 1:
            bar_page("Funding by fiscal year",
                     {f"FY{k}": v for k, v in agg["funding_by_fy"].items()}, vertical=True)
        if scope.get("group_by") or scope.get("date_from"):
            wk = reporter.by_period(items, scope.get("group_by") or "week", "funding")
            bar_page(f"Funding by {scope.get('group_by') or 'week'}", wk,
                     vertical=True, line=len(wk) > 8)
        bar_page("Funding by Institute / Center", agg.get("funding_by_ic"))
        bar_page("Funding by activity code / mechanism", agg.get("funding_by_activity"))
        bar_page("Funding by application type", agg.get("funding_by_app_type"))
        if len(agg.get("funding_by_org") or {}) > 1:
            bar_page("Funding by organization", agg.get("funding_by_org"))
    return buf.getvalue()


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


_DIM_FIELD = {"ic": "ic", "activity": "activity_code", "app_type": "app_type",
              "org": "org", "state": "state"}

# Interactive graph-explorer dimensions: label -> dimension key.
_EXP_DIMS = {
    "Fiscal year": "fy",
    "Institute (IC)": "ic",
    "Activity code / mechanism": "activity",
    "Application type": "app_type",
    "Organization": "org",
    "State": "state",
    "Week (new awards)": "week",
    "Month (new awards)": "month",
}
_DIM_TO_LABEL = {v: k for k, v in _EXP_DIMS.items()}


def _default_view(question: str, scope: dict, agg: dict):
    """Pick the graph view (dimension label, metric label) that matches the
    question. The reasoned parse's chart hint wins; then an explicit dimension
    named in the text; then the pulled scope."""
    q = (question or "").lower()
    scope = scope or {}
    if scope.get("chart_metric"):
        metric = "Funding ($)" if scope["chart_metric"] == "funding" else "Award count"
    else:
        metric = "Award count" if any(w in q for w in _COUNT_WORDS) else "Funding ($)"

    # 0) The chart hint from the reasoned parse — it read the whole question.
    _hint = scope.get("chart_dim")
    if _hint in _DIM_TO_LABEL:
        return _DIM_TO_LABEL[_hint], metric

    # 1) Explicit dimension named in the question takes priority.
    if any(w in q for w in ("weekly", "per week", "by week", "each week", "week-by-week")):
        return "Week (new awards)", metric
    if any(w in q for w in ("monthly", "per month", "by month", "each month")):
        return "Month (new awards)", metric
    if any(w in q for w in ("fiscal year", "by year", "per year", "each year", "by fy",
                            "per fy", "year over year", "year-over-year", "over the years",
                            "annual", "yearly", "trend", "over time")):
        return "Fiscal year", metric
    for label, dim in (("Institute (IC)", "ic"),
                       ("Activity code / mechanism", "activity"),
                       ("Application type", "app_type"),
                       ("Organization", "org"), ("State", "state")):
        if any(k in q for k in _DIM_KEYS[dim][0]):
            return label, metric

    # 2) No explicit dimension -> infer from the pulled scope.
    if scope.get("group_by") == "week" or (scope.get("date_from")
                                           and not scope.get("fiscal_years")):
        return "Week (new awards)", metric
    if scope.get("group_by") == "month":
        return "Month (new awards)", metric
    if len(scope.get("fiscal_years") or []) > 1:
        return "Fiscal year", metric
    return "Institute (IC)", metric


def _chart_png(title: str, data: dict, kind: str, money: bool) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    navy, ink = "#012169", "#1d1d1f"
    labels, vals = list(data), list(data.values())
    fig, ax = plt.subplots(figsize=(8, 4.6))
    if kind == "time" and len(data) > 8:
        ax.plot(labels, vals, color=navy, linewidth=2, marker="o", markersize=4)
        ax.tick_params(axis="x", rotation=45)
        if money:
            ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
    elif kind == "time":
        ax.bar(labels, vals, color=navy)
        ax.tick_params(axis="x", rotation=45)
        if money:
            ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
    else:
        ax.barh(labels[::-1], vals[::-1], color=navy)
        if money:
            ax.xaxis.set_major_formatter(FuncFormatter(_money_fmt))
    ax.set_title(title, color=navy, fontsize=13, fontweight="bold", loc="left", pad=12)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(colors=ink, labelsize=9)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


# Categorical dimension -> (funding_key, count_key, label) for building a view.
_CAT_VIEW = {
    "ic": ("funding_by_ic", "by_ic", "institute / center"),
    "activity": ("funding_by_activity", "by_activity", "mechanism"),
    "app_type": ("funding_by_app_type", "by_app_type", "application type"),
    "org": ("funding_by_org", "by_org", "institution"),
    "state": ("funding_by_state", "by_state", "state"),
}


def plot_series(series: pd.Series, kind: str):
    """Draw a series with the chart form that fits its job: a long time series
    is a trend (line), a short one is vertical bars, and categories are
    horizontal bars ranked top-down."""
    if kind == "time" and len(series) > 8:
        st.line_chart(series, color=EMORY_BLUE, height=300)
    elif kind == "time":
        st.bar_chart(series, color=EMORY_BLUE, height=300)
    else:
        st.bar_chart(series, color=EMORY_BLUE, horizontal=True,
                     height=max(160, 30 * len(series)))


def _view_series(dim: str, items: list, agg: dict, is_funding: bool):
    """Build one chart's data for a dimension. Returns (series, kind, title) —
    kind is 'time' or 'cat' — or None when there's nothing to plot."""
    ylabel = "Funding ($)" if is_funding else "Awards"
    if dim in ("week", "month"):
        data = reporter.by_period(items, dim, "funding" if is_funding else "count")
        return (pd.Series(data, name=ylabel), "time", f"{ylabel} by {dim}") if data else None
    if dim == "fy":
        raw = agg.get("funding_by_fy") if is_funding else agg.get("by_fy")
        data = {f"FY{k}": v for k, v in (raw or {}).items()}
        return (pd.Series(data, name=ylabel), "time",
                f"{ylabel} by fiscal year") if data else None
    fk, ck, lbl = _CAT_VIEW[dim]
    raw = (agg.get(fk) if is_funding else agg.get(ck)) or {}
    data = {str(k): v for k, v in list(raw.items())[:15]}
    return (pd.Series(data, name=ylabel), "cat",
            f"{ylabel} by {lbl}") if data else None


def complementary_charts(items: list, scope: dict, agg: dict, primary_dim: str,
                         is_funding: bool, limit: int = 2):
    """Render up to `limit` extra charts on dimensions DISTINCT from the primary
    one — only when they have at least two categories of real data, so a report
    shows more than one graph when it genuinely adds insight (and just one when
    it doesn't). Returns the number of extra charts drawn."""
    fys = [y for y in (scope.get("fiscal_years") or []) if str(y).isdigit()]
    multi_year = len(set(fys)) > 1
    if primary_dim in ("week", "month", "fy"):
        order = ["ic", "activity", "app_type"]
    elif primary_dim == "ic":
        order = (["fy"] if multi_year else []) + ["activity", "app_type"]
    else:
        order = ["ic"] + (["fy"] if multi_year else []) + ["activity"]

    specs = []
    for dim in order:
        if dim == primary_dim:
            continue
        spec = _view_series(dim, items, agg, is_funding)
        if not spec or len(spec[0]) < 2:  # one bar isn't a useful extra view
            continue
        specs.append(spec)
        if len(specs) >= limit:
            break
    if not specs:
        return 0
    st.caption("Other useful views of this same data")
    for series, kind, title in specs:
        st.markdown(f"**{title}**")
        plot_series(series, kind)
    return len(specs)


def chart_explorer(items: list, question: str, scope: dict, key_prefix="exp"):
    """A graph with a smart default plus controls to flip the breakdown/metric.
    Computes its own aggregate from the items it's handed, so it always matches
    that exact dataset (the report's own snapshot)."""
    agg = reporter.aggregate(items or [])
    dlabel, mlabel = _default_view(question, scope, agg)
    labels = list(_EXP_DIMS)
    st.markdown("**View as a graph**")
    c1, c2 = st.columns([2, 1])
    sel = c1.selectbox("Break down by", labels, index=labels.index(dlabel),
                       key=f"{key_prefix}_dim", label_visibility="collapsed")
    metric = c2.radio("Measure", ["Funding ($)", "Award count"],
                      index=0 if mlabel.startswith("Funding") else 1, horizontal=True,
                      key=f"{key_prefix}_metric", label_visibility="collapsed")
    d = _EXP_DIMS[sel]
    is_f = metric.startswith("Funding")
    st.caption(f"{metric} by {sel} — for the data above: "
               f"{st.session_state.get('rep_query', '')}")
    spec = _view_series(d, items, agg, is_f)
    if not spec:
        st.caption("No data for this view.")
        return d, is_f
    series, kind, title = spec
    plot_series(series, kind)
    try:
        st.download_button("Download chart (PNG)",
                           _chart_png(title, series.to_dict(), kind, is_f),
                           file_name="nih_chart.png", mime="image/png",
                           key=f"{key_prefix}_png")
    except Exception:  # noqa: BLE001 - PNG is best-effort
        pass
    return d, is_f


def maybe_chart(question: str, items: list, scope: dict = None):
    """Render a chart that matches what the text/scope is about, from the exact
    items handed in (so each follow-up charts its own data snapshot)."""
    scope = scope or {}
    agg = reporter.aggregate(items or [])
    q = (question or "").lower()
    _graph_intent = _CHART_WORDS + (
        "by ", "per ", "across", "breakdown", "break down", "distribution",
        "split", "share", "top ", "largest", "leading", "dominant", "funding",
        "spending", "compare", "comparison", "trend", "over time", "rank")
    hint = scope.get("chart_dim")
    _dim_hit = any(any(k in q for k in kw) for _d, (kw, *_rest) in _DIM_KEYS.items())
    if not (any(w in q for w in _graph_intent) or _dim_hit or hint):
        return None
    metric = scope.get("chart_metric") or (
        "count" if any(w in q for w in _COUNT_WORDS)
        else "funding" if any(w in q for w in _FUND_WORDS) else "funding")

    fys = sorted({int(y) for y in (scope.get("fiscal_years") or []) if str(y).isdigit()})
    has_range = bool(scope.get("date_from") or scope.get("date_to"))
    if fys:
        window = "FY " + ", ".join(str(y) for y in sorted(fys, reverse=True))
    elif has_range:
        window = f"{scope.get('date_from') or '…'} → {scope.get('date_to') or '…'}"
    else:
        window = ""
    wsfx = f" — {window}" if window else ""

    # 1) Time series: the parse's chart hint, explicit weekly/monthly wording,
    #    or a calendar date range (-> weekly).
    period = hint if hint in ("week", "month") else scope.get("group_by")
    if any(w in q for w in ("weekly", "per week", "by week", "each week",
                            "week over week", "week-by-week")):
        period = "week"
    elif any(w in q for w in ("monthly", "per month", "by month", "each month",
                              "month over month")):
        period = "month"
    elif not period and has_range:
        period = "week"
    if period:
        pmetric = scope.get("chart_metric") or (
            "count" if any(w in q for w in _COUNT_WORDS)
            else "funding" if any(w in q for w in _FUND_WORDS) else "count")
        data = reporter.by_period(items, period, pmetric)
        if data:
            ylabel = "Funding ($)" if pmetric == "funding" else "New awards"
            st.markdown(f"**{ylabel} by {period}**{wsfx}")
            plot_series(pd.Series(data, name=ylabel), "time")
            return period, pmetric == "funding"

    dim = hint if hint in ("fy", "ic", "activity", "app_type", "org", "state") else \
        next((d for d, (kw, *_) in _DIM_KEYS.items() if any(k in q for k in kw)), None)
    cat_dim = dim if dim and dim != "fy" else \
        next((d for d, (kw, *_) in _DIM_KEYS.items()
              if d != "fy" and any(k in q for k in kw)), None)

    # 2) Multiple fiscal years -> a year comparison (grouped by category, or a trend).
    multi_year = len(fys) > 1
    if multi_year:
        if cat_dim:
            xt = reporter.funding_crosstab(items, _DIM_FIELD[cat_dim])
            top = sorted(xt, key=lambda c: sum(xt[c].values()), reverse=True)[:10]
            yrs = sorted({y for c in xt for y in xt[c]})
            df = pd.DataFrame({f"FY{y}": [xt[c].get(y, 0) for c in top] for y in yrs},
                              index=[str(c) for c in top])
            st.markdown(f"**Funding ($) by {_DIM_KEYS[cat_dim][3]} and fiscal year**")
            st.bar_chart(df, stack=False, height=max(200, 34 * len(top)), horizontal=True)
            return cat_dim, True
        d = agg.get("funding_by_fy") if metric == "funding" else agg.get("by_fy")
        if d:
            ylabel = "Funding ($)" if metric == "funding" else "Awards"
            st.markdown(f"**{ylabel} by fiscal year**")
            plot_series(pd.Series({f"FY{k}": v for k, v in d.items()}, name=ylabel),
                        "time")
            return "fy", metric == "funding"

    # 3) Single fiscal year / no multi-year -> a breakdown within that window,
    #    titled with the window so it lines up with the text.
    if dim is None or dim == "fy":
        dim = "ic"
    _, fund_key, count_key, dim_label = _DIM_KEYS[dim]
    data = agg.get(fund_key if metric == "funding" else count_key) or {}
    if not data:
        data = agg.get("funding_by_ic") or agg.get("by_ic") or {}
        dim_label = "Institute / Center"
    rows = list(data.items())[:15]
    if not rows:
        return None
    ylabel = "Funding ($)" if metric == "funding" else "Awards"
    st.markdown(f"**{ylabel} by {dim_label}**{wsfx}")
    plot_series(pd.Series({str(k): v for k, v in rows}, name=ylabel), "cat")
    return dim, metric == "funding"


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
    d_from = parsed.get("date_from")
    d_to = parsed.get("date_to")
    eff_topic = parsed.get("topic") or ""
    eff_pi = parsed.get("pi_name") or ""
    eff_ic = parsed.get("ic_codes") or None
    eff_act = parsed.get("activity_codes") or None
    eff_newly = bool(parsed.get("newly_added"))
    # Record ceiling. Multi-year (fiscal-year) pulls return one row per project
    # PER YEAR, so they need a high cap or prior years get truncated by the
    # newest-first sort. Day-window pulls are small.
    if fys:
        limit = 14000          # ~ up to the API's offset ceiling; paginated
    elif eff_active:
        limit = 8000
    elif d_from or d_to:
        limit = 4000
    elif days:
        limit = 800
    else:
        limit = 2000
    # No window in the question -> no time filter at all (all available data),
    # rather than imposing a default window the user didn't ask for.
    awards, err = reporter.fetch_awards(
        org_names=o_names, pi_name=eff_pi, text_query=eff_topic,
        ic_codes=eff_ic, activity_codes=eff_act, org_states=None,
        award_min=None, award_max=None,
        use_award_window=bool(days),
        days_back=days or 7, fiscal_years=fys, newly_added_only=eff_newly,
        active_only=eff_active, date_from=d_from, date_to=d_to, limit=limit)
    parts = [o_names[0] if o_names else "All institutions"]
    if eff_pi:
        parts.append(f"PI: {eff_pi}")
    if eff_topic:
        parts.append(f"topic: {eff_topic}")
    if eff_ic:
        parts.append("IC: " + ", ".join(eff_ic))
    if eff_act:
        parts.append("mech: " + ", ".join(eff_act))
    if d_from or d_to:
        parts.append(f"{d_from or '…'} → {d_to or '…'}")
    elif fys:
        parts.append("FY " + ", ".join(str(y) for y in sorted(fys, reverse=True)))
    elif days:
        parts.append(f"last {days} days")
    if eff_active:
        parts.append("active grants only")
    if parsed.get("group_by"):
        parts.append(f"by {parsed['group_by']}")
    if not (fys or days or eff_active or d_from or d_to):
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


DEFAULT_PEERS = ["EMORY UNIVERSITY", "DUKE UNIVERSITY", "VANDERBILT UNIVERSITY",
                 "JOHNS HOPKINS UNIVERSITY", "WASHINGTON UNIVERSITY",
                 "UNIVERSITY OF PITTSBURGH"]
_BENCH_WORDS = ("benchmark", "peer", "peers", "compared to other", "vs other",
                "versus other", "against other institution", "how does emory compare",
                "compare emory", "relative to peer", "other institutions",
                "other universities", "nationally ranked", "rank among")
_PEER_NAMES = {
    "duke": "DUKE UNIVERSITY", "vanderbilt": "VANDERBILT UNIVERSITY",
    "johns hopkins": "JOHNS HOPKINS UNIVERSITY", "hopkins": "JOHNS HOPKINS UNIVERSITY",
    "washington university": "WASHINGTON UNIVERSITY", "wustl": "WASHINGTON UNIVERSITY",
    "washu": "WASHINGTON UNIVERSITY", "pittsburgh": "UNIVERSITY OF PITTSBURGH",
    "pitt": "UNIVERSITY OF PITTSBURGH", "stanford": "STANFORD UNIVERSITY",
    "yale": "YALE UNIVERSITY", "penn": "UNIVERSITY OF PENNSYLVANIA",
    "michigan": "UNIVERSITY OF MICHIGAN AT ANN ARBOR",
    "ucsf": "UNIVERSITY OF CALIFORNIA, SAN FRANCISCO",
    "unc": "UNIV OF NORTH CAROLINA CHAPEL HILL",
}


def maybe_benchmark(question: str, scope: dict):
    """If the question asks to benchmark Emory against peers, compare total NIH
    funding across institutions for the same scope. Returns {rows, errors, fys}
    or None."""
    q = (question or "").lower()
    named = [v for k, v in _PEER_NAMES.items() if k in q]
    wants = any(w in q for w in _BENCH_WORDS) or (
        named and any(w in q for w in ("compare", "vs ", "versus", "benchmark", "against")))
    if not wants:
        return None
    orgs = ["EMORY UNIVERSITY"] + (named or [o for o in DEFAULT_PEERS
                                             if o != "EMORY UNIVERSITY"])
    seen = set()
    orgs = [o for o in orgs if not (o in seen or seen.add(o))]
    fys = scope.get("fiscal_years") or [CURRENT_FY]
    with st.spinner(_stage("bench")):
        rows, errs = reporter.compare_orgs(
            orgs, text_query=scope.get("topic") or "",
            ic_codes=scope.get("ic_codes") or None, fiscal_years=fys, limit=4000)
    return {"rows": rows, "errors": errs, "fys": fys}


def run_report(q: str, reading: str = ""):
    """Parse the question, pull the matching awards, and write the report.
    ``reading`` is the triage step's one-sentence interpretation of the request;
    it anchors the parse and the answer so all stages work from the same intent.
    Progress renders as a staged research log rather than a generic spinner."""
    qa = q + (f"\n\n[The request was read as: {reading}]" if reading else "")
    with st.status("🔬 Researching your question…", expanded=True) as _prog:
        st.write(f"_{_stage('parse')}_")
        parsed, _ = summarize.parse_query(
            qa, CURRENT_FY, list(reporter.IC_CHOICES), list(reporter.ACTIVITY_CHOICES))
        st.write(f"_{_stage('fetch')}_")
        awards, err, label = ai_fetch(parsed)
        st.session_state.rep_sample = bool(err)
        if err:
            awards = reporter.sample_awards()
        st.session_state.rep_items = awards
        st.session_state.rep_query = label
        st.session_state.last_parsed = parsed   # scope drives charts + follow-ups
        st.session_state.filter_sig = filter_sig()
        st.write(f"_🧮 Cross-tabulating {len(awards)} award record(s)…_")
        bench = maybe_benchmark(qa, parsed)
        st.session_state.benchmark = bench
        facts = build_facts(awards, qa)
        if bench and bench.get("rows"):
            facts += ("\n\nPeer benchmark — total NIH funding by institution for FY "
                      + ", ".join(str(y) for y in bench["fys"]) + ": "
                      + "; ".join(f"{r['org']}: {reporter.fmt_money(r['total_amount'])} "
                                  f"({r['awards']} awards)" for r in bench["rows"]))
        st.write(f"_{_stage('write')}_")
        answer, engine = summarize.custom_report(qa, facts)
        _prog.update(label="🔬 Analysis complete", state="complete", expanded=False)
    st.session_state.ask_answer = answer
    st.session_state.ask_engine = engine
    st.session_state.asked_question = q
    st.session_state.report_reading = reading
    try:
        st.query_params["q"] = q  # reflect in the URL for a shareable link
    except Exception:  # noqa: BLE001
        pass
    st.session_state.follow_thread = []
    # New report id so the graph explorer gets fresh widgets (and its scope-matched
    # default), instead of keeping the previous report's selection.
    st.session_state.report_seq = st.session_state.get("report_seq", 0) + 1
    for _k in ("clarify_q", "clarify_for", "clarify_reading", "clarify_conf",
               "suggestions", "report_pdf"):
        st.session_state.pop(_k, None)


def _within_days(date_str: str, days: int) -> bool:
    try:
        d = datetime.strptime((date_str or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    return (datetime.now().date() - d).days <= days


def run_exec_briefing():
    """One-click weekly executive briefing: this week's new awards in the
    context of recent weeks, plus fiscal-year-to-date — an AI summary of both
    up top and 10+ graphs below."""
    with st.status("🔬 Compiling the weekly executive briefing…", expanded=True) as _prog:
        st.write(f"_{_stage('fetch')}_")
        wk_all, wk_err = reporter.fetch_awards(
            org_names=[reporter.DEFAULT_ORG], use_award_window=True,
            days_back=70, limit=2000)
        fy_items, fy_err = reporter.fetch_awards(
            org_names=[reporter.DEFAULT_ORG], use_award_window=False,
            fiscal_years=[CURRENT_FY], limit=8000)
        if wk_err and fy_err:
            st.error(f"NIH RePORTER is unreachable right now ({fy_err}).")
            _prog.update(label="Briefing unavailable", state="error")
            return
        week_items = [it for it in (wk_all or [])
                      if _within_days(it.get("award_date"), 7)]
        st.write(f"_{_stage('crunch')}_")
        facts = ("SECTION A — THIS WEEK (awards issued in the last 7 days):\n"
                 + build_facts(week_items)
                 + "\n\nSECTION B — RECENT WEEKS (last ~10 weeks, for context):\n"
                 + build_facts(wk_all or [])
                 + f"\n\nSECTION C — FISCAL YEAR TO DATE (FY{CURRENT_FY}):\n"
                 + build_facts(fy_items or []))
        st.write(f"_{_stage('write')}_")
        q = (f"Write a weekly executive summary for Emory research leadership, "
             f"dated {datetime.now():%B %d, %Y}. Two parts: (1) THIS WEEK — how "
             "many new NIH awards, total dollars, the most notable awards (PI, "
             "institute, amount), and whether the week is above or below the "
             "recent weekly pace; (2) FISCAL YEAR TO DATE — total awards and "
             "dollars, the leading institutes and mechanisms, and any momentum "
             "or concentration worth flagging. Crisp and executive in tone; "
             "many charts follow below, so keep the narrative tight.")
        ans, eng = summarize.custom_report(q, facts)
        _prog.update(label="🔬 Briefing ready", state="complete", expanded=False)
    st.session_state.exec_brief = {
        "summary": ans, "engine": eng, "wk": wk_all or [],
        "week": week_items, "fy": fy_items or [],
        "note": (f"Recent-weeks pull failed ({wk_err})." if wk_err else
                 f"FY pull failed ({fy_err})." if fy_err else ""),
        "date": datetime.now().strftime("%B %d, %Y"),
    }


def _top_pi_funding(items: list, n: int = 12) -> dict:
    pf: dict = {}
    for it in items:
        p = (it.get("contact_pi") or it.get("pi") or "").strip()
        if p:
            pf[p] = pf.get(p, 0) + int(it.get("amount") or 0)
    return dict(sorted(pf.items(), key=lambda kv: kv[1], reverse=True)[:n])


def _exec_charts(eb: dict) -> list:
    """Build the briefing's chart list: (title, series, kind) — weekly context
    first, then the fiscal year. Only charts with real data are included."""
    wk_all, week, fy = eb["wk"], eb["week"], eb["fy"]
    charts = []

    def add(title, data, kind, money=False):
        if data and len(data) >= (2 if kind != "cat" else 1):
            name = "Funding ($)" if money else "Awards"
            charts.append((title, pd.Series(
                {str(k): v for k, v in list(data.items())[:15]}, name=name), kind))

    add("New awards by week — last ~10 weeks",
        reporter.by_period(wk_all, "week", "count"), "time")
    add("Funding by week — last ~10 weeks",
        reporter.by_period(wk_all, "week", "funding"), "time", money=True)
    aw = reporter.aggregate(week)
    add("This week — funding by institute", aw.get("funding_by_ic"), "cat", money=True)
    add("This week — awards by mechanism", aw.get("by_activity"), "cat")
    af = reporter.aggregate(fy)
    add(f"FY{CURRENT_FY} — funding by month",
        reporter.by_period(fy, "month", "funding"), "time", money=True)
    add(f"FY{CURRENT_FY} — new awards by month",
        reporter.by_period(fy, "month", "count"), "time")
    add(f"FY{CURRENT_FY} — funding by institute", af.get("funding_by_ic"),
        "cat", money=True)
    add(f"FY{CURRENT_FY} — awards by institute", af.get("by_ic"), "cat")
    add(f"FY{CURRENT_FY} — funding by mechanism", af.get("funding_by_activity"),
        "cat", money=True)
    add(f"FY{CURRENT_FY} — funding by application type",
        af.get("funding_by_app_type"), "cat", money=True)
    add(f"FY{CURRENT_FY} — top investigators by funding", _top_pi_funding(fy),
        "cat", money=True)
    largest = {f"{(it.get('contact_pi') or it.get('pi') or '?').split(';')[0][:28]} · "
               f"{it.get('ic', '')}": int(it.get("amount") or 0)
               for it in sorted(fy, key=lambda i: int(i.get("amount") or 0),
                                reverse=True)[:10]}
    add(f"FY{CURRENT_FY} — largest awards", largest, "cat", money=True)
    return charts


def render_exec_brief():
    eb = st.session_state.exec_brief
    st.subheader("Weekly executive briefing")
    st.caption(f"Week ending {eb['date']} · {reporter.DEFAULT_ORG.title()} · "
               "NIH RePORTER")
    if eb.get("note"):
        st.warning(eb["note"])
    aw, af = reporter.aggregate(eb["week"]), reporter.aggregate(eb["fy"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("New awards this week", aw["count"])
    m2.metric("Funding this week", reporter.fmt_money(aw["total_amount"]))
    m3.metric(f"FY{CURRENT_FY} awards to date", af["count"])
    m4.metric(f"FY{CURRENT_FY} funding to date",
              reporter.fmt_money(af["total_amount"]))
    with st.container(border=True):
        ai_md(eb["summary"])
        if eb.get("engine") == "claude":
            st.caption(f"Engine: Claude ({summarize.MODEL}) · figures pre-computed")
    charts = _exec_charts(eb)
    st.markdown(f"### The week and the year in {len(charts)} graphs")
    cols = st.columns(2)
    for i, (title, series, kind) in enumerate(charts):
        with cols[i % 2]:
            st.markdown(f"**{title}**")
            plot_series(series, kind)
    st.download_button("Download briefing (Markdown)", eb["summary"],
                       file_name="nih_weekly_executive_briefing.md",
                       mime="text/markdown")
    st.write("")
    if st.button("＋ New query", type="primary", key="newq_exec",
                 help="Clear the briefing and start a new question."):
        reset_query()


# Suggested one-click next steps shown under a report (label, follow-up prompt).
# Fallback when the AI can't tailor suggestions — one trend, one mix, one
# comparison, one strategic angle.
NEXT_STEPS = [
    ("Trend over years", "Show the trend over the last 5 fiscal years as a chart, "
     "and note whether it is growing or shrinking."),
    ("Concentration risk", "How concentrated is this funding among the top PIs and "
     "the largest institute? Quote the shares and what they imply."),
    ("Peer benchmark", "Benchmark this against peer institutions (Duke, Vanderbilt, "
     "Johns Hopkins) with a comparison chart."),
    ("Renewal pipeline", "Which of these projects end within the next 12 months, "
     "and how many dollars are at stake?"),
]

_REFETCH_WORDS = (
    "also", "add", "include", "as well", "plus", "instead", "expand", "wider",
    "broaden", "previous year", "prior year", "more year", "earlier year",
    "all institution", "nationwide", "across institution", "every institution",
    "pull", "go back", "fetch", "since", "back to", "all years", "every year",
    "last ", "past ", "fiscal year", "fy20", "fy 20", " in 20", "this year",
    "other institution", "another institution", "compare to", "vs ", "versus")


def _needs_refetch(fparsed: dict, fq: str) -> bool:
    ql = fq.lower()
    if any(fparsed.get(k) for k in ("fiscal_years", "date_from", "date_to",
                                    "all_institutions", "organization", "active_only",
                                    "days_back", "ic_codes", "activity_codes",
                                    "pi_name", "topic")):
        return True
    return any(w in ql for w in _REFETCH_WORDS)


# Phrasings that signal the follow-up is a brand-new search, not a refinement of
# the current result set — so we should NOT inherit the old filters.
_FRESH_WORDS = ("instead", "rather", "new search", "start over", "starting over",
                "from scratch", "switch to", "switch the", "change to", "forget",
                "ignore the previous", "ignore previous", "ignore that", "reset",
                "brand new", "different institution", "different university",
                "different topic", "different question", "never mind", "nevermind",
                "scratch that", "actually, ", "let's look at", "now show me")
# Phrasings that keep us anchored to the SAME result set (a true refinement).
_REFINE_WORDS = ("of those", "of these", "of that", "of the above", "within that",
                 "within these", "within those", "among those", "among these",
                 "from that set", "from those", "in that set", "drill", "break "
                 "down", "break it down", "broken down", "same set", "same data",
                 "also", "add", "include", "as well", "plus", "both")


def _is_fresh_search(base: dict, fparsed: dict, fq: str) -> bool:
    """True when a follow-up should run as a NEW search rather than inherit the
    original filters. Triggers on explicit 'new search' language or when the
    follow-up names a different institution / topic / PI than the current pull.
    Refinement language ('of those', 'break down', 'also') always stays anchored."""
    ql = fq.lower()
    if any(w in ql for w in _REFINE_WORDS):
        return False
    if any(w in ql for w in _FRESH_WORDS):
        return True
    # A different explicit institution / topic / PI focus = a new search.
    if fparsed.get("all_institutions") and not base.get("all_institutions"):
        return True
    for k in ("organization", "topic", "pi_name"):
        nv = (fparsed.get(k) or "").strip().lower()
        if not nv:
            continue
        bv = (base.get(k) or "").strip().lower()
        if nv != bv:  # naming a focus the base didn't have, or a different one
            return True
    return False


def _merge_parse(base: dict, add: dict, fq: str) -> dict:
    """Merge follow-up criteria over the original. Lists union when the follow-up
    is additive ('also/add/include'), otherwise the follow-up replaces."""
    additive = any(w in fq.lower() for w in ("also", "add", "include", "as well",
                                             "plus", "both", "and "))
    merged = dict(base or {})
    for k, v in (add or {}).items():
        if isinstance(v, list):
            if v:
                if additive and k in ("fiscal_years", "ic_codes", "activity_codes"):
                    merged[k] = sorted(set(merged.get(k) or []) | set(v))
                else:
                    merged[k] = v
        elif isinstance(v, bool):
            if v:
                merged[k] = True
        elif v not in (None, ""):
            merged[k] = v
    return merged


def run_followup(fq: str):
    """Answer a follow-up through the same reasoned path as the original query:
    plan how the scope changes (constraints added, changed, or removed), refetch
    only when needed, then answer. Each turn keeps its OWN data snapshot/scope
    so its chart matches its own answer (without disturbing the main report)."""
    note = ""
    items = st.session_state.get("rep_items") or []
    scope = st.session_state.get("last_parsed") or {}
    label = st.session_state.get("rep_query", "")
    # The conversation so far — built up front so BOTH the scope planner and
    # the answer see it: the planner resolves references ('that year', 'those
    # grants'), the answer relates the follow-up to what was already said.
    prior = ["Original question: " + st.session_state.get(
                 "asked_question", st.session_state.get("ask_question", "")),
             "Original answer: " + st.session_state.get("ask_answer", "")[:1800]]
    for t in st.session_state.get("follow_thread", [])[-4:]:
        prior += ["Follow-up question: " + t["q"], "Answer: " + t["a"][:1200]]
    history = "\n".join(p[:500] for p in prior)  # condensed for the planner
    with st.status("🔬 Working on the follow-up…", expanded=True) as _prog:
        st.write(f"_{_stage('parse')}_")
        # Same reasoning path as the original query: the model sees the CURRENT
        # scope, the conversation, and decides whether the pulled data answers
        # the follow-up (reuse) or the scope must change (refetch) — adding,
        # changing, or REMOVING constraints as the follow-up implies.
        plan = summarize.plan_followup(
            fq, scope, CURRENT_FY, list(reporter.IC_CHOICES),
            list(reporter.ACTIVITY_CHOICES), n_items=len(items),
            history=history)
        if plan:
            if plan["action"] == "refetch":
                st.write(f"_{_stage('fetch')}_")
                awards, err, label2 = ai_fetch(plan["scope"])
                if not err and awards:
                    items, scope, label = awards, plan["scope"], label2
                    note = f"_Scope updated for this follow-up: {label}._\n\n"
            else:
                scope = plan["scope"]  # same data; chart hints may have moved
        else:
            # No API key / planner error: fall back to the keyword heuristics.
            fparsed, _ = summarize.parse_query(
                fq, CURRENT_FY, list(reporter.IC_CHOICES),
                list(reporter.ACTIVITY_CHOICES))
            if _needs_refetch(fparsed, fq):
                fresh = _is_fresh_search(scope, fparsed, fq)
                merged = fparsed if fresh else _merge_parse(scope, fparsed, fq)
                st.write("_🧭 New direction — starting a fresh search…_" if fresh
                         else f"_{_stage('fetch')}_")
                awards, err, label2 = ai_fetch(merged)
                if not err and awards:
                    items, scope, label = awards, merged, label2
                    note = (f"_New search: {label}._\n\n" if fresh
                            else f"_Pulled data for: {label}._\n\n")
        st.write(f"_{_stage('write')}_")
        ans, eng = summarize.custom_report(fq, build_facts(items, fq),
                                           prior="\n\n".join(prior))
        _prog.update(label="🔬 Follow-up ready", state="complete", expanded=False)
    st.session_state.setdefault("follow_thread", []).append(
        {"q": fq, "a": note + ans, "engine": eng, "items": items,
         "scope": scope, "query": label})


# Fetch whenever the filters change (or on first load), so the AI answers and
# reports always reflect the current filters — no stale data, no button needed.
if "rep_items" not in st.session_state or st.session_state.get("filter_sig") != filter_sig():
    with st.spinner("🔭 Scanning the latest NIH award notices…"):
        awards, rep_err = run_query()
    store_results(awards, rep_err)

rep_items = st.session_state.get("rep_items") or []

# These notices belong to a produced report — never block the start screen.
if st.session_state.get("ask_answer"):
    if st.session_state.get("rep_sample"):
        st.warning("Live NIH RePORTER API unreachable right now "
                   f"({st.session_state.get('rep_error')}); showing bundled sample "
                   "awards so the report still renders.")
    if not rep_items:
        st.info("This query matched no NIH awards. Try a longer look-back, broader "
                "terms, fewer filters, or a fiscal year.")

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

if st.session_state.get("exec_brief"):
    # ----- One-click weekly executive briefing view -----
    render_exec_brief()

elif not st.session_state.get("ask_answer"):
    # Shareable link: a ?q=… in the URL auto-runs that report once on load.
    _qp = st.query_params.get("q")
    if _qp and not st.session_state.get("_q_consumed"):
        st.session_state._q_consumed = True
        run_report(_qp)
        st.rerun()
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
        if st.button("📊 Weekly executive briefing — this week + FY to date, "
                     "10+ graphs", use_container_width=True, key="exec_btn"):
            run_exec_briefing()
            st.rerun()

    st.write("")
    # Smaller example buttons so the input box stands out. Examples are well-formed,
    # so they skip the clarification check.
    ex_cols = st.columns([1] + [2] * len(EXAMPLE_REPORTS) + [1])
    for col, (label, q) in zip(ex_cols[1:-1], EXAMPLE_REPORTS):
        if col.button(label, use_container_width=True, key=f"ex_{label}"):
            st.session_state.pending_q = q
            st.session_state.run_ask = True
            st.session_state.skip_clarify = True
            st.rerun()

    # ---- Saved reports (this session) ----
    _saved = st.session_state.get("saved") or []
    if _saved:
        _sl, _sc, _sr = st.columns([1, 2.4, 1])
        with _sc:
            with st.expander(f"⭐ Saved reports ({len(_saved)})"):
                for _si, _s in enumerate(_saved):
                    _r, _x = st.columns([6, 1])
                    if _r.button(_s["q"][:80], key=f"saved_{_si}",
                                 use_container_width=True):
                        run_report(_s["q"])
                        st.rerun()
                    if _x.button("✕", key=f"unsave_{_si}"):
                        _saved.pop(_si)
                        st.rerun()

    # ---- Clarification: if the request is ambiguous, ask BEFORE running it ----
    if st.session_state.get("clarify_q"):
        _cl, _cc, _cr = st.columns([1, 2.4, 1])
        with _cc:
            _reading = st.session_state.get("clarify_reading", "")
            _conf = st.session_state.get("clarify_conf")
            _head = "**Before I run this, a quick check**"
            if isinstance(_conf, int):
                _head += f" — I'm about {_conf}% sure I've read it right"
            body = _head + ".\n\n"
            if _reading:
                body += f"My best reading: _{_reading}_\n\n"
            body += "**" + st.session_state["clarify_q"] + "**"
            st.info(body)
            with st.form("clarify_form", clear_on_submit=False):
                clar_ans = st.text_input("Your answer", label_visibility="collapsed",
                                         placeholder="Type your answer…")
                cf1, cf2 = st.columns(2)
                cont = cf1.form_submit_button("Use my answer", type="primary",
                                              use_container_width=True)
                anyway = cf2.form_submit_button(
                    "That reading is right — run it" if _reading
                    else "Run it as asked", use_container_width=True)
            st.caption("**Use my answer**: run the report with what you typed. "
                       "The other button runs it now using the reading above.")
        if cont and clar_ans.strip():
            run_report(st.session_state["clarify_for"]
                       + f"\n\n[Clarification] {st.session_state['clarify_q']} "
                       + f"User's answer: {clar_ans.strip()}")
            st.rerun()
        elif anyway:
            run_report(st.session_state["clarify_for"],
                       reading=st.session_state.get("clarify_reading", ""))
            st.rerun()

    elif (ask_clicked and st.session_state.ask_question.strip()) \
            or st.session_state.pop("run_ask", False):
        q = st.session_state.ask_question
        skip = st.session_state.pop("skip_clarify", False)
        tri = dict(summarize._NO_CLARIFY)
        if not skip:
            with st.spinner(_stage("clarify")):
                tri = summarize.clarify(q)
        if tri.get("question"):
            # Not confident enough in a single reading — ask BEFORE running,
            # and show the best reading so the user can simply confirm it.
            st.session_state.clarify_q = tri["question"]
            st.session_state.clarify_for = q
            st.session_state.clarify_reading = tri.get("reading", "")
            st.session_state.clarify_conf = tri.get("confidence", 0)
            st.rerun()
        else:
            # Confident reading — run it, and carry the reading through so the
            # data pull and the narrative work from the same interpretation.
            run_report(q, reading=tri.get("reading", ""))
            st.rerun()

else:
    # ----- Report view: the top search box is hidden; report + follow-up lead. -----
    st.subheader("Your report")
    st.caption("Question: " + st.session_state.get("asked_question",
                                                   st.session_state.get("ask_question", "")))
    if st.session_state.get("report_reading"):
        st.caption("🧭 Read as: " + st.session_state["report_reading"])
    st.caption("🔗 Shareable: the link in your browser's address bar reopens this "
               "report — copy it to share.")
    with st.container(border=True):
        ai_md(st.session_state.ask_answer)
        st.caption("Covering: " + st.session_state.get("rep_query", ""))
        if st.session_state.get("ask_engine") == "claude":
            st.caption(f"Engine: Claude ({summarize.MODEL}) · figures pre-computed")
    _prim = chart_explorer(rep_items,
                           st.session_state.get("asked_question",
                                                st.session_state.get("ask_question", "")),
                           st.session_state.get("last_parsed"),
                           key_prefix=f"main{st.session_state.get('report_seq', 0)}")
    if _prim:
        complementary_charts(rep_items, st.session_state.get("last_parsed") or {},
                             agg, _prim[0], _prim[1], limit=2)

    _bench = st.session_state.get("benchmark")
    if _bench and _bench.get("rows"):
        st.markdown("**Peer benchmark — total NIH funding** (FY "
                    + ", ".join(str(y) for y in _bench["fys"]) + ")")
        _bd = {r["org"].title(): r["total_amount"] for r in _bench["rows"]}
        st.bar_chart(pd.Series(_bd, name="Funding ($)"), color=EMORY_BLUE,
                     horizontal=True, height=max(160, 34 * len(_bd)))
        if _bench.get("errors"):
            st.caption("Some peers couldn't be fetched: "
                       + "; ".join(_bench["errors"][:2]))

    with st.expander("Export this report  ·  Excel · PDF · Markdown"):
        dlc1, dlc2, dlc3 = st.columns(3)
        if xlsx_data:
            dlc1.download_button("Data (Excel)", xlsx_data,
                                 file_name="nih_reporter_data.xlsx", mime=XLSX_MIME,
                                 use_container_width=True,
                                 help="Every grant in this result set, with all "
                                      "fields, investigator roles, breakdowns, charts.")
        dlc2.download_button("Report (Markdown)", st.session_state.ask_answer,
                             file_name="nih_report.md", mime="text/markdown",
                             use_container_width=True)
        if st.session_state.get("report_pdf"):
            dlc3.download_button("PDF (with graphs)", st.session_state.report_pdf,
                                 file_name="nih_reporter_report.pdf",
                                 mime="application/pdf", use_container_width=True)
        elif dlc3.button("Create PDF report", use_container_width=True,
                         help="Narrative plus several bar charts."):
            try:
                with st.spinner("📊 Compositing the narrative and charts into a PDF…"):
                    st.session_state.report_pdf = build_pdf(
                        rep_items, agg, st.session_state.get("rep_query", ""),
                        st.session_state.ask_answer, st.session_state.get("last_parsed"))
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"PDF build failed: {exc}")

        st.divider()
        st.markdown("**Email this report**")
        _smtp = _secret("SMTP_HOST")
        em1, em2 = st.columns([3, 1])
        _to = em1.text_input("Recipient email(s), comma-separated",
                             key="email_to", label_visibility="collapsed",
                             placeholder="name@emory.edu", disabled=not _smtp)
        if em2.button("Send", use_container_width=True, disabled=not _smtp):
            if not _to.strip():
                st.warning("Enter at least one recipient.")
            else:
                try:
                    title = "NIH RePORTER report — " + datetime.now().strftime("%b %d, %Y")
                    notify.send_email(
                        _smtp, int(_secret("SMTP_PORT", "587")),
                        _secret("SMTP_USERNAME"), _secret("SMTP_PASSWORD"),
                        _secret("ALERT_EMAIL_FROM", "nih-reporter@emory.edu"),
                        _to.strip(), rep_items[:60],
                        summary_md=st.session_state.ask_answer, title=title)
                    st.success(f"Sent to {_to.strip()}.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Email failed: {exc}")
        if not _smtp:
            st.caption("Set SMTP_HOST + SMTP_USERNAME/SMTP_PASSWORD (and optionally "
                       "ALERT_EMAIL_FROM) in Streamlit secrets to enable emailing.")

        st.divider()
        if st.button("⭐ Save this report", key="save_report"):
            saved = st.session_state.setdefault("saved", [])
            qn = st.session_state.get("asked_question", "")
            if qn and not any(s["q"] == qn for s in saved):
                saved.append({"q": qn, "label": st.session_state.get("rep_query", "")})
                st.toast("Saved. Find it on the start screen (New query).", icon="⭐")
            else:
                st.caption("Already saved.")

    # ---- Suggested next steps: tailored, graph-leaning ideas for this data ----
    if "suggestions" not in st.session_state:
        try:
            st.session_state.suggestions = summarize.suggest_followups(
                st.session_state.get("asked_question", ""), build_facts(rep_items))
        except Exception:  # noqa: BLE001
            st.session_state.suggestions = NEXT_STEPS
    suggestions = st.session_state.suggestions or NEXT_STEPS
    st.caption("Suggested next steps — ideas you might not have considered")
    ns_cols = st.columns(len(suggestions))
    for _i, (_nc, (_lbl, _fq)) in enumerate(zip(ns_cols, suggestions)):
        if _nc.button(_lbl, key=f"ns_{_i}_{_lbl}", use_container_width=True):
            run_followup(_fq)
            st.rerun()

    # ---- Follow-up: builds on the original question + the data it produced ----
    st.markdown("### Ask a follow-up about this report")
    st.caption("Refinements like 'of those, which are at the med school' reuse the "
               "data above; if you point somewhere new — a different institution, "
               "topic, or 'start a new search' — it pulls fresh data automatically.")
    # The conversation so far renders first; the input box always sits at the
    # very bottom, directly under the most recent answer.
    for _ti, turn in enumerate(st.session_state.get("follow_thread", [])):
        st.markdown(f"**Follow-up:** {turn['q']}")
        with st.container(border=True):
            ai_md(turn["a"])
            # Chart this turn's OWN data snapshot (matches its answer).
            _fitems = turn.get("items", rep_items)
            _fscope = turn.get("scope") or {}
            _fprim = maybe_chart(turn["q"], _fitems, _fscope)
            if _fprim:
                complementary_charts(_fitems, _fscope, reporter.aggregate(_fitems),
                                     _fprim[0], _fprim[1], limit=1)

    with st.form("followup_form", clear_on_submit=True):
        follow_q = st.text_input(
            "Follow-up question", label_visibility="collapsed",
            placeholder="e.g. Of those, which are at the School of Medicine? "
                        "Break the total down by mechanism.")
        follow_go = st.form_submit_button("Ask follow-up")
    if follow_go and follow_q.strip():
        run_followup(follow_q)
        st.rerun()

    st.write("")
    if st.button("＋ New query", type="primary", key="newq_bottom",
                 help="Clear everything and start a new question."):
        reset_query()

# The data dashboard and manual filters belong to the report view only — the
# start screen stays just the search box and example reports.
if not st.session_state.get("ask_answer"):
    st.stop()

# ============================ Manual filters (optional, at the bottom) ============================
render_filters()
