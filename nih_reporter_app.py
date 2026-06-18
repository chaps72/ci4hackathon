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
ACCENT = "#012169"        # Emory navy (links, tabs, charts) — professional, not bright
ACCENT_HOVER = "#1c3a8f"  # lighter navy
ACCENT_2 = "#8a94ad"      # muted steel-blue secondary chart series
INK = "#1d1d1f"           # Apple near-black text
MUTED = "#6e6e73"         # Apple secondary text
BORDER = "#d2d2d7"        # Apple hairline
PANEL = "#f5f5f7"         # Apple light gray
# Chart colors (names kept for existing references).
EMORY_BLUE = ACCENT
EMORY_LIGHT_BLUE = ACCENT_HOVER
EMORY_GOLD = ACCENT_2
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
/* New query buttons: soft pastel-Emory fill (targeted by their widget keys) */
.st-key-newq_top button, .st-key-newq_bottom button {{
    background: #e7ecf7 !important; color: {EMORY_NAVY} !important;
    border: 1px solid #d4ddf0 !important;
}}
.st-key-newq_top button:hover, .st-key-newq_bottom button:hover {{
    background: #d8e2f4 !important; color: {EMORY_NAVY} !important;
    border-color: #bcc9ea !important;
}}
.stTabs [data-baseweb="tab-list"] {{ gap: 8px; border-bottom: 1px solid {BORDER}; }}
.stTabs [aria-selected="true"] {{ color: {ACCENT} !important; font-weight: 600; }}
a {{ color: {ACCENT}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
[data-testid="stMetricValue"], .stDataFrame {{ font-variant-numeric: tabular-nums; }}
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


st.markdown(
    f'<div class="nih-header">{_emory_brand()}'
    '<h1>NIH RePORTER</h1>'
    '<p>NIH/HHS award intelligence · live from the NIH RePORTER API</p></div>',
    unsafe_allow_html=True)

_RESET_KEYS = ("ask_answer", "ask_engine", "follow_thread", "ask_question",
               "asked_question", "clarify_q", "clarify_for", "skip_clarify",
               "suggestions", "report_pdf")


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

        def bar_page(title, d, vertical=False, money=True, top=12):
            if not d:
                return
            rows = list(d.items())[:top]
            labels = [str(k) for k, _ in rows]
            vals = [v for _, v in rows]
            fig, ax = plt.subplots(figsize=(8.5, 5.6))
            if vertical:
                ax.bar(labels, vals, color=navy)
                ax.tick_params(axis="x", rotation=45)
                (ax.yaxis if money else ax.yaxis).set_major_formatter(
                    FuncFormatter(_money_fmt)) if money else None
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
            bar_page(f"Funding by {scope.get('group_by') or 'week'}", wk, vertical=True)
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

# Interactive graph-explorer dimensions: label -> (dim, count_key, funding_key).
_EXP_DIMS = {
    "Fiscal year": ("fy", "by_fy", "funding_by_fy"),
    "Institute (IC)": ("ic", "by_ic", "funding_by_ic"),
    "Activity code / mechanism": ("activity", "by_activity", "funding_by_activity"),
    "Application type": ("app_type", "by_app_type", "funding_by_app_type"),
    "Organization": ("org", "by_org", "funding_by_org"),
    "State": ("state", "by_state", "funding_by_state"),
    "Week (new awards)": ("week", None, None),
    "Month (new awards)": ("month", None, None),
}


def _default_view(question: str, scope: dict, agg: dict):
    """Pick the graph view (dimension label, metric label) that matches the text.
    An explicit dimension in the question wins; otherwise fall back to the scope."""
    q = (question or "").lower()
    scope = scope or {}
    metric = "Award count" if any(w in q for w in _COUNT_WORDS) else "Funding ($)"

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


def _chart_png(title: str, data: dict, vertical: bool, money: bool) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    navy, ink = "#012169", "#1d1d1f"
    labels, vals = list(data), list(data.values())
    fig, ax = plt.subplots(figsize=(8, 4.6))
    if vertical:
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
    d, count_key, fund_key = _EXP_DIMS[sel]
    is_f = metric.startswith("Funding")
    ylabel = "Funding ($)" if is_f else "Awards"
    st.caption(f"{metric} by {sel} — for the data above: "
               f"{st.session_state.get('rep_query', '')}")
    if d in ("week", "month"):
        data = reporter.by_period(items, d, "funding" if is_f else "count")
        vertical, title = True, f"{ylabel} by {d}"
    elif d == "fy":
        raw = agg.get("funding_by_fy") if is_f else agg.get("by_fy")
        data = {f"FY{k}": v for k, v in (raw or {}).items()}
        vertical, title = True, f"{ylabel} by fiscal year"
    else:
        raw = (agg.get(fund_key) if is_f else agg.get(count_key)) or {}
        data = {str(k): v for k, v in list(raw.items())[:15]}
        vertical, title = False, f"{ylabel} by {sel}"
    if not data:
        st.caption("No data for this view.")
        return
    st.bar_chart(pd.Series(data, name=ylabel), color=EMORY_BLUE,
                 horizontal=not vertical,
                 height=320 if vertical else max(180, 32 * len(data)))
    try:
        st.download_button("Download chart (PNG)",
                           _chart_png(title, data, vertical, is_f),
                           file_name="nih_chart.png", mime="image/png",
                           key=f"{key_prefix}_png")
    except Exception:  # noqa: BLE001 - PNG is best-effort
        pass


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
    _dim_hit = any(any(k in q for k in kw) for _d, (kw, *_rest) in _DIM_KEYS.items())
    if not (any(w in q for w in _graph_intent) or _dim_hit):
        return
    metric = ("count" if any(w in q for w in _COUNT_WORDS)
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

    # 1) Time series: explicit weekly/monthly, or a calendar date range (-> weekly).
    period = scope.get("group_by")
    if any(w in q for w in ("weekly", "per week", "by week", "each week",
                            "week over week", "week-by-week")):
        period = "week"
    elif any(w in q for w in ("monthly", "per month", "by month", "each month",
                              "month over month")):
        period = "month"
    elif not period and has_range:
        period = "week"
    if period:
        pmetric = "count" if any(w in q for w in _COUNT_WORDS) else \
            ("funding" if any(w in q for w in _FUND_WORDS) else "count")
        data = reporter.by_period(items, period, pmetric)
        if data:
            ylabel = "Funding ($)" if pmetric == "funding" else "New awards"
            st.markdown(f"**{ylabel} by {period}**{wsfx}")
            st.bar_chart(pd.Series(data, name=ylabel), color=EMORY_BLUE, height=300)
            return

    dim = next((d for d, (kw, *_) in _DIM_KEYS.items() if any(k in q for k in kw)), None)
    cat_dim = next((d for d, (kw, *_) in _DIM_KEYS.items()
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
            return
        d = agg.get("funding_by_fy") if metric == "funding" else agg.get("by_fy")
        if d:
            ylabel = "Funding ($)" if metric == "funding" else "Awards"
            st.markdown(f"**{ylabel} by fiscal year**")
            st.bar_chart(pd.Series({f"FY{k}": v for k, v in d.items()}, name=ylabel),
                         color=EMORY_BLUE, height=300)
            return

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
        return
    ylabel = "Funding ($)" if metric == "funding" else "Awards"
    st.markdown(f"**{ylabel} by {dim_label}**{wsfx}")
    st.bar_chart(pd.Series({str(k): v for k, v in rows}, name=ylabel),
                 color=EMORY_BLUE, horizontal=True, height=max(160, 30 * len(rows)))


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


def run_report(q: str):
    """Parse the question, pull the matching awards, and write the report."""
    with st.spinner("Reading your request and pulling the matching awards..."):
        parsed, _ = summarize.parse_query(
            q, CURRENT_FY, list(reporter.IC_CHOICES), list(reporter.ACTIVITY_CHOICES))
        awards, err, label = ai_fetch(parsed)
        st.session_state.rep_sample = bool(err)
        if err:
            awards = reporter.sample_awards()
        st.session_state.rep_items = awards
        st.session_state.rep_query = label
        st.session_state.last_parsed = parsed   # scope drives charts + follow-ups
        st.session_state.filter_sig = filter_sig()
    with st.spinner("Analyzing the data..."):
        answer, engine = summarize.custom_report(q, build_facts(awards, q))
    st.session_state.ask_answer = answer
    st.session_state.ask_engine = engine
    st.session_state.asked_question = q
    try:
        st.query_params["q"] = q  # reflect in the URL for a shareable link
    except Exception:  # noqa: BLE001
        pass
    st.session_state.follow_thread = []
    # New report id so the graph explorer gets fresh widgets (and its scope-matched
    # default), instead of keeping the previous report's selection.
    st.session_state.report_seq = st.session_state.get("report_seq", 0) + 1
    for _k in ("clarify_q", "clarify_for", "suggestions", "report_pdf"):
        st.session_state.pop(_k, None)


# Suggested one-click next steps shown under a report (label, follow-up prompt).
NEXT_STEPS = [
    ("Plot a chart", "Plot the most relevant breakdown of this data as a bar chart."),
    ("By institute", "Break this down by NIH institute (IC) and show a bar chart."),
    ("By mechanism", "Break this down by activity code / mechanism and show a bar chart."),
    ("By fiscal year", "Show this by fiscal year as a bar chart."),
    ("Top PIs", "List the top principal investigators by total funding."),
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
    """Answer a follow-up. If it needs data the original pull didn't include, go
    back and pull that data first. Each turn keeps its OWN data snapshot/scope so
    its chart matches its own answer (without disturbing the main report)."""
    note = ""
    items = st.session_state.get("rep_items") or []
    scope = st.session_state.get("last_parsed") or {}
    label = st.session_state.get("rep_query", "")
    fparsed, _ = summarize.parse_query(
        fq, CURRENT_FY, list(reporter.IC_CHOICES), list(reporter.ACTIVITY_CHOICES))
    if _needs_refetch(fparsed, fq):
        merged = _merge_parse(scope, fparsed, fq)
        with st.spinner("Pulling the data needed for this…"):
            awards, err, label2 = ai_fetch(merged)
        if not err and awards:
            items, scope, label = awards, merged, label2
            note = f"_Pulled data for: {label}._\n\n"
    prior = ["Original question: " + st.session_state.get(
                 "asked_question", st.session_state.get("ask_question", "")),
             "Original answer: " + st.session_state.get("ask_answer", "")[:1800]]
    for t in st.session_state.get("follow_thread", [])[-4:]:
        prior += ["Follow-up question: " + t["q"], "Answer: " + t["a"][:1200]]
    with st.spinner("Working on it…"):
        ans, eng = summarize.custom_report(fq, build_facts(items, fq),
                                           prior="\n\n".join(prior))
    st.session_state.setdefault("follow_thread", []).append(
        {"q": fq, "a": note + ans, "engine": eng, "items": items,
         "scope": scope, "query": label})


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

    # ---- Clarification: if the request is ambiguous, ask BEFORE running it ----
    if st.session_state.get("clarify_q"):
        _cl, _cc, _cr = st.columns([1, 2.4, 1])
        with _cc:
            st.info("**Quick clarification** — " + st.session_state["clarify_q"])
            with st.form("clarify_form", clear_on_submit=False):
                clar_ans = st.text_input("Your answer", label_visibility="collapsed",
                                         placeholder="Type your answer…")
                cf1, cf2 = st.columns(2)
                cont = cf1.form_submit_button("Use my answer", type="primary",
                                              use_container_width=True)
                anyway = cf2.form_submit_button("Skip — use defaults",
                                                use_container_width=True)
            st.caption("**Use my answer**: run the report using what you typed above. "
                       "**Skip — use defaults**: run it now without answering "
                       "(home institution = Emory, all available data).")
        if cont and clar_ans.strip():
            run_report(st.session_state["clarify_for"]
                       + f"\n\n[Clarification] {st.session_state['clarify_q']} "
                       + f"User's answer: {clar_ans.strip()}")
            st.rerun()
        elif anyway:
            run_report(st.session_state["clarify_for"])
            st.rerun()

    elif (ask_clicked and st.session_state.ask_question.strip()) \
            or st.session_state.pop("run_ask", False):
        q = st.session_state.ask_question
        skip = st.session_state.pop("skip_clarify", False)
        cq = ""
        if not skip:
            with st.spinner("Reading your request…"):
                cq = summarize.clarify(q)
        if cq:
            # Ask first; don't run the report until the user answers.
            st.session_state.clarify_q = cq
            st.session_state.clarify_for = q
            st.rerun()
        else:
            run_report(q)
            st.rerun()

else:
    # ----- Report view: the top search box is hidden; report + follow-up lead. -----
    st.subheader("Your report")
    st.caption("Question: " + st.session_state.get("asked_question",
                                                   st.session_state.get("ask_question", "")))
    st.caption("🔗 Shareable: the link in your browser's address bar reopens this "
               "report — copy it to share.")
    with st.container(border=True):
        ai_md(st.session_state.ask_answer)
        st.caption("Covering: " + st.session_state.get("rep_query", ""))
        if st.session_state.get("ask_engine") == "claude":
            st.caption(f"Engine: Claude ({summarize.MODEL}) · figures pre-computed")
    chart_explorer(rep_items,
                   st.session_state.get("asked_question",
                                        st.session_state.get("ask_question", "")),
                   st.session_state.get("last_parsed"),
                   key_prefix=f"main{st.session_state.get('report_seq', 0)}")
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
                with st.spinner("Building the PDF report…"):
                    st.session_state.report_pdf = build_pdf(
                        rep_items, agg, st.session_state.get("rep_query", ""),
                        st.session_state.ask_answer, st.session_state.get("last_parsed"))
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"PDF build failed: {exc}")

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
    for _i, (_col, (_lbl, _fq)) in enumerate(zip(ns_cols, suggestions)):
        if _col.button(_lbl, key=f"ns_{_i}_{_lbl}", use_container_width=True):
            run_followup(_fq)
            st.rerun()

    # ---- Follow-up: builds on the original question + the data it produced ----
    st.markdown("### Ask a follow-up about this report")
    st.caption("Builds on the question and the exact data above — same result set, "
               "no new search.")
    # The conversation so far renders first; the input box always sits at the
    # very bottom, directly under the most recent answer.
    for _ti, turn in enumerate(st.session_state.get("follow_thread", [])):
        st.markdown(f"**Follow-up:** {turn['q']}")
        with st.container(border=True):
            ai_md(turn["a"])
            # Chart this turn's OWN data snapshot (matches its answer).
            maybe_chart(turn["q"], turn.get("items", rep_items), turn.get("scope"))

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
