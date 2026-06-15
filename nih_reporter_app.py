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
                   layout="wide", initial_sidebar_state="expanded")

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
    '<div class="nih-header"><h1>🔬 NIH RePORTER Weekly Report</h1>'
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


# ============================ Sidebar: search ============================
with st.sidebar:
    st.title("Build the report")
    mode = st.radio(
        "Report mode",
        ["My institution's new awards", "Topic search (all institutions)"],
        help="Institution mode focuses on one organization's new awards; topic "
             "mode scans every NIH-funded institution.")
    org_mode = mode.startswith("My institution")

    with st.expander("🏛️ Institution & people", expanded=True):
        org_name = st.text_input(
            "Organization", value=reporter.DEFAULT_ORG, disabled=not org_mode,
            help="Exact NIH RePORTER org name, e.g. 'EMORY UNIVERSITY'.")
        pi_name = st.text_input("Principal investigator", value="",
                                placeholder="e.g. Smith, Jane")

    with st.expander("🔎 Topic", expanded=not org_mode):
        topic = st.text_input(
            "Research terms", value="" if org_mode else "vaccine immunology",
            placeholder="e.g. gene therapy, Alzheimer's, CRISPR",
            help="Matched against project title, abstract, and terms.")

    with st.expander("💰 Funding mechanism"):
        ic_codes = st.multiselect(
            "Institute / Center (IC)", options=list(reporter.IC_CHOICES.keys()),
            format_func=lambda c: f"{c} — {reporter.IC_CHOICES[c]}",
            help="Administering NIH Institute or Center.")
        activity_codes = st.multiselect(
            "Activity code", options=list(reporter.ACTIVITY_CHOICES.keys()),
            format_func=lambda c: f"{c} — {reporter.ACTIVITY_CHOICES[c]}",
            help="Grant mechanism, e.g. R01, R21, K99.")

    with st.expander("📍 Geography & award size"):
        states = st.multiselect(
            "Organization state(s)",
            ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
             "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
             "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
             "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
             "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR"],
            disabled=org_mode,
            help="Most useful in topic mode; institution mode is already one org.")
        amt = st.slider("Award size ($K)", 0, 5000, (0, 5000), step=50,
                        help="Filter by total award amount. 5000 = no upper limit.")
        award_min = amt[0] * 1000 if amt[0] > 0 else None
        award_max = amt[1] * 1000 if amt[1] < 5000 else None

    with st.expander("🗓️ Time window", expanded=True):
        rep_days = st.slider("Look back (days)", 7, 120, 7)
        fy_now = datetime.now().year
        fiscal_years = st.multiselect(
            "Fiscal year(s)", list(range(fy_now, fy_now - 6, -1)), default=[],
            help="Leave empty to use the award-notice date window only.")
        newly_added = st.checkbox(
            "Newly added to RePORTER only", value=False,
            help="Only projects recently added to the database — true 'new this "
                 "week' signal.")
    rep_limit = st.slider("Max awards", 25, 500, 200, step=25)

    pull = st.button("Pull awards", type="primary", use_container_width=True)
    st.caption("🤖 Claude summaries enabled." if summarize.claude_available()
               else "ℹ️ No ANTHROPIC_API_KEY — template summaries.")


def run_query():
    return reporter.fetch_awards(
        org_names=[org_name] if (org_mode and org_name.strip()) else None,
        pi_name=pi_name, text_query=topic,
        ic_codes=ic_codes or None, activity_codes=activity_codes or None,
        org_states=states or None, award_min=award_min, award_max=award_max,
        days_back=rep_days, fiscal_years=fiscal_years or None,
        newly_added_only=newly_added, limit=rep_limit)


if pull:
    with st.spinner("Querying NIH RePORTER..."):
        awards, rep_err = run_query()
    used_sample = False
    if rep_err:
        awards, used_sample = reporter.sample_awards(), True
    st.session_state.rep_items = awards
    st.session_state.rep_error = rep_err
    st.session_state.rep_sample = used_sample
    filt = []
    if org_mode and org_name.strip():
        filt.append(org_name.strip())
    else:
        filt.append("All institutions")
    for label, val in (("PI", pi_name), ("topic", topic),
                       ("IC", ", ".join(ic_codes)),
                       ("mech", ", ".join(activity_codes)),
                       ("states", ", ".join(states))):
        if val:
            filt.append(f"{label}: {val}")
    filt.append(f"last {rep_days}d")
    st.session_state.rep_query = " · ".join(filt)
    st.session_state.pop("rep_summary", None)

rep_items = st.session_state.get("rep_items")

if rep_items is None:
    st.info("Set your filters in the sidebar and click **Pull awards** to build "
            "the weekly report.")
    st.stop()

if st.session_state.get("rep_sample"):
    st.warning(f"Live NIH RePORTER API unreachable from this environment "
               f"({st.session_state.get('rep_error')}); showing bundled sample "
               "awards so the report still renders. (Benchmarking needs the live API.)")

if not rep_items:
    st.warning("No NIH awards matched these filters. Try a longer look-back, "
               "broader terms, fewer filters, or add a fiscal year.")
    st.stop()

agg = reporter.aggregate(rep_items)
st.caption("Query: " + st.session_state.get("rep_query", ""))

# ---------- KPI row ----------
k1, k2, k3, k4, k5 = st.columns(5)
kpi(k1, "Awards", f"{agg['count']:,}")
kpi(k2, "Total funding", reporter.fmt_money(agg["total_amount"]))
kpi(k3, "Median award", reporter.fmt_money(agg["median_amount"]))
kpi(k4, "Largest award", reporter.fmt_money(agg["max_amount"]))
kpi(k5, "Institutes", str(len(agg["by_ic"])),
    sub=" · ".join(list(agg["by_ic"])[:3]))
st.write("")

tab_overview, tab_awards, tab_board, tab_bench, tab_ask, tab_report = st.tabs(
    ["📊 Overview", "📋 Awards", "🏆 Leaderboards", "⚖️ Benchmark",
     "🧠 Ask (AI)", "📤 Report"])

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
        "⬇️ Export awards (CSV)",
        df[["award_date", "ic", "activity_code", "app_type", "amount", "pi",
            "org", "state", "project_num", "fiscal_year", "title", "url"]]
        .to_csv(index=False),
        file_name="nih_reporter_awards.csv", mime="text/csv")

    with st.expander(f"📄 Award detail cards ({len(rep_items)})"):
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

# ============================ Ask (AI) ============================
def build_facts(items: list) -> str:
    a = reporter.aggregate(items)
    dist = reporter.grant_count_distribution(items, thresholds=(1, 2, 3, 4, 5, 6))
    exact = {}
    for c in dist["counts"].values():
        exact[c] = exact.get(c, 0) + 1
    lines = [
        f"Filters: {st.session_state.get('rep_query', '')}.",
        f"Awards in result set: {a['count']}. Total funding: {reporter.fmt_money(a['total_amount'])}. "
        f"Median award: {reporter.fmt_money(a['median_amount'])}. Largest: {reporter.fmt_money(a['max_amount'])}.",
        f"Distinct principal investigators: {len(dist['counts'])}.",
        "Investigators by number of grants where they are listed PI (this result set):",
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
    return "\n".join(lines)


with tab_ask:
    st.subheader("Ask a question about this data")
    st.caption("Answers use **only** exact figures computed from the current result "
               "set. For investigator-level questions (e.g. who holds 3+ grants), "
               "widen the look-back or pick a full fiscal year so each PI's grants "
               "are all captured — counts reflect this pull, not full careers.")

    dist = reporter.grant_count_distribution(rep_items, thresholds=(2, 3, 4, 5))
    st.markdown("**Key numbers — investigators by grants held as PI**")
    kq = st.columns(5)
    kpi(kq[0], "Distinct PIs", str(len(reporter.pi_award_counts(rep_items))))
    for col, t in zip(kq[1:], (2, 3, 4, 5)):
        kpi(col, f"≥ {t} grants", str(dist["at_least"][t]))

    counts = reporter.pi_award_counts(rep_items)
    multi = [{"Investigator": n, "Grants as PI": c}
             for n, c in counts.most_common() if c >= 2]
    if multi:
        with st.expander(f"Investigators with 2+ grants ({len(multi)})"):
            st.dataframe(pd.DataFrame(multi), hide_index=True, use_container_width=True)
    else:
        st.caption("No investigator holds more than one grant in this result set — "
                   "widen the window or pick a fiscal year.")

    st.divider()
    question = st.text_area(
        "Your request",
        value="How many Emory investigators have 3 or more grants where they are "
              "PI, and how many have 4 or more? List them.",
        height=90)
    if st.button("🧠 Generate report", type="primary"):
        with st.spinner("Analyzing..."):
            answer, engine = summarize.custom_report(question, build_facts(rep_items))
        st.session_state.ask_answer = answer
        st.session_state.ask_engine = engine
    if st.session_state.get("ask_answer"):
        st.markdown(st.session_state.ask_answer)
        if st.session_state.get("ask_engine") == "claude":
            st.caption(f"Engine: Claude ({summarize.MODEL}) · figures pre-computed")
            st.download_button("⬇️ Download answer (Markdown)", st.session_state.ask_answer,
                               file_name="nih_custom_report.md", mime="text/markdown")


# ============================ Report / delivery ============================
with tab_report:
    st.subheader("Narrative summary & delivery")
    if st.button("📝 Generate summary", type="primary"):
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
        d1.download_button("⬇️ Summary (Markdown)", st.session_state.rep_summary,
                           file_name="nih_reporter_summary.md", mime="text/markdown")
        d2.download_button("⬇️ HTML digest",
                           emailer.build_html(rep_items, st.session_state.rep_summary, rep_title),
                           file_name="nih_reporter_digest.html", mime="text/html")
        d3.download_button("⬇️ Email (.eml)",
                           emailer.build_eml(rep_items, st.session_state.rep_summary, rep_title),
                           file_name="nih_reporter_digest.eml", mime="message/rfc822")

        st.divider()
        st.markdown("**Post to a channel**")
        teams_hook = _secret("TEAMS_WEBHOOK_URL")
        slack_hook = _secret("SLACK_WEBHOOK_URL")
        p1, p2 = st.columns(2)
        if p1.button("📨 Post to Teams", disabled=not teams_hook,
                     help="Set TEAMS_WEBHOOK_URL in secrets to enable."):
            try:
                notify.send_teams_summary(teams_hook, st.session_state.rep_summary, title=rep_title)
                st.success("Posted to Teams.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Teams post failed: {exc}")
        if p2.button("💬 Post to Slack", disabled=not slack_hook,
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
