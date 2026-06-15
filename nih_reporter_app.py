"""NIH RePORTER Weekly Report - standalone Streamlit app.

A self-contained weekly report of recently issued NIH/HHS awards, pulled live
from the NIH RePORTER API (https://api.reporter.nih.gov/ - free, no key).
Runs independently of the FedWatch dashboard; both share fedwatch/reporter.py.

Run with:  streamlit run nih_reporter_app.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from fedwatch import emailer, reporter, summarize

st.set_page_config(page_title="NIH RePORTER Weekly Report", page_icon="🔬", layout="wide")

# ---------- Emory brand styling ----------
EMORY_BLUE = "#012169"
EMORY_GOLD = "#f2a900"
EMORY_LIGHT_BLUE = "#007dba"

st.markdown(f"""<style>
h1, h2, h3 {{ color: {EMORY_BLUE} !important; font-family: Georgia, 'Times New Roman', serif; }}
[data-testid="stSidebar"] {{ background: #f7f8fb; border-right: 1px solid #e3e7ee; }}
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
a {{ color: {EMORY_LIGHT_BLUE}; }}
.nih-header {{
    background: linear-gradient(135deg, {EMORY_BLUE} 0%, #02297f 100%);
    border-bottom: 4px solid {EMORY_GOLD};
    border-radius: 10px; padding: 16px 24px 12px 24px; margin-bottom: 16px;
}}
.nih-header h1 {{ color: #ffffff !important; margin: 0; font-size: 1.7rem; }}
.nih-header p {{ color: #d6deef; margin: 4px 0 0 0; font-size: 0.9rem; }}
</style>""", unsafe_allow_html=True)

st.markdown(
    '<div class="nih-header"><h1>🔬 NIH RePORTER Weekly Report</h1>'
    '<p>Recently issued NIH/HHS awards, live from the NIH RePORTER API · '
    'Office of the SVPR</p></div>', unsafe_allow_html=True)


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return d or ""


# ---------- Controls ----------
with st.sidebar:
    st.title("Report settings")
    mode = st.radio(
        "Report mode",
        ["My institution's new awards", "Topic search (all institutions)"],
        help="Switch between one institution's new awards and a keyword scan "
             "across every NIH-funded institution.")
    org_mode = mode.startswith("My institution")

    org_name = st.text_input(
        "Organization", value=reporter.DEFAULT_ORG, disabled=not org_mode,
        help="Exact NIH RePORTER org name, e.g. 'EMORY UNIVERSITY'.")
    topic = st.text_input(
        "Research terms", value="" if org_mode else "vaccine immunology",
        placeholder="e.g. gene therapy, Alzheimer's, CRISPR",
        help="Matched against project title, terms, and abstract. Optional in "
             "institution mode to narrow the portfolio to a topic.")
    rep_days = st.slider("Look back (days)", 7, 90, 7)

    fy_now = datetime.now().year
    fiscal_years = st.multiselect(
        "Fiscal year(s)", list(range(fy_now, fy_now - 6, -1)), default=[],
        help="Leave empty to use the award-notice date window only.")
    rep_limit = st.slider("Max awards", 25, 500, 200, step=25)

    pull = st.button("Pull awards", type="primary", use_container_width=True)

    st.divider()
    st.caption("🤖 Claude summaries enabled." if summarize.claude_available()
               else "ℹ️ No ANTHROPIC_API_KEY - template summaries.")

if pull:
    with st.spinner("Querying NIH RePORTER..."):
        awards, rep_err = reporter.fetch_awards(
            org_names=[org_name] if (org_mode and org_name.strip()) else None,
            text_query=topic,
            days_back=rep_days,
            fiscal_years=fiscal_years or None,
            limit=rep_limit,
        )
    used_sample = False
    if rep_err:
        # Live API unreachable (e.g. no network) - fall back to bundled sample.
        awards = reporter.sample_awards()
        used_sample = True
    st.session_state.rep_items = awards
    st.session_state.rep_error = rep_err
    st.session_state.rep_sample = used_sample
    st.session_state.rep_query = (
        (f"{org_name} · " if org_mode else "All institutions · ")
        + (topic.strip() or "all topics") + f" · last {rep_days}d")
    st.session_state.pop("rep_summary", None)

rep_items = st.session_state.get("rep_items")

if rep_items is None:
    st.info("Set your filters in the sidebar and click **Pull awards** to build "
            "the weekly report.")
    st.stop()

if not rep_items:
    st.warning("No NIH awards matched in this window. Try a longer look-back, "
               "broader terms, or add a fiscal year.")
    st.stop()

if st.session_state.get("rep_sample"):
    st.warning(f"Live NIH RePORTER API unreachable from this environment "
               f"({st.session_state.get('rep_error')}); showing bundled sample "
               "awards so the report still renders.")

# ---------- Report ----------
agg = reporter.aggregate(rep_items)
st.caption("Query: " + st.session_state.get("rep_query", ""))
m1, m2, m3 = st.columns(3)
m1.metric("Awards", agg["count"])
m2.metric("Total funding", reporter.fmt_money(agg["total_amount"]))
m3.metric("Funding ICs", len(agg["by_ic"]))
if agg["by_ic"]:
    st.caption("By institute/center: "
               + " · ".join(f"{k} ({v})" for k, v in agg["by_ic"].items()))

st.divider()

for it in rep_items:
    label = (f":blue[**{it.get('ic', 'NIH')}**] · "
             f"{fmt_date(it.get('award_date') or it.get('date', ''))} · "
             f"{reporter.fmt_money(it.get('amount'))} · {it.get('title', '')[:90]}")
    with st.expander(label):
        st.markdown(f"**{it.get('title', '')}**")
        meta_bits = [b for b in (
            it.get("pi") and f"PI: {it['pi']}",
            it.get("org"),
            it.get("project_num"),
            it.get("fiscal_year") and f"FY{it['fiscal_year']}",
        ) if b]
        st.caption(" · ".join(meta_bits))
        period = f"{it.get('start') or '?'} – {it.get('end') or '?'}"
        st.markdown(f"**{reporter.fmt_money(it.get('amount'))}** · Project period {period}"
                    + (f" · Award notice {it['award_date']}" if it.get("award_date") else ""))
        if it.get("abstract"):
            st.write(it["abstract"][:1200] + ("…" if len(it["abstract"]) > 1200 else ""))
        if it.get("url"):
            st.markdown(f"[Open in NIH RePORTER ↗]({it['url']})")

st.divider()
rep_df = pd.DataFrame(rep_items)[
    ["award_date", "ic", "amount", "pi", "org", "project_num",
     "fiscal_year", "title", "url"]]
c1, c2 = st.columns(2)
c1.download_button("⬇️ Export awards (CSV)", rep_df.to_csv(index=False),
                   file_name="nih_reporter_awards.csv", mime="text/csv")

if c2.button("📝 Summarize this report"):
    with st.spinner("Writing the weekly award summary..."):
        text, engine = summarize.generate_summary(
            rep_items, style="Executive summary",
            extra_instructions=(
                "These are newly issued NIH research awards, not policy items. "
                "Lead with the funding totals and notable awards (largest dollar "
                "amounts, prominent institutes), group by research theme, and name "
                "PIs and institutes. Do not invent figures."))
    st.session_state.rep_summary = text
    st.session_state.rep_summary_engine = engine

if st.session_state.get("rep_summary"):
    st.markdown(st.session_state.rep_summary)
    st.caption(f"Engine: {'Claude (' + summarize.MODEL + ')' if st.session_state.get('rep_summary_engine') == 'claude' else 'template'}")
    s1, s2 = st.columns(2)
    s1.download_button("⬇️ Summary (Markdown)", st.session_state.rep_summary,
                       file_name="nih_reporter_summary.md", mime="text/markdown")
    rep_title = "NIH RePORTER Weekly Award Report - " + datetime.now().strftime("%b %d, %Y")
    s2.download_button(
        "⬇️ Email digest (.eml)",
        emailer.build_eml(rep_items, st.session_state.rep_summary, rep_title),
        file_name="nih_reporter_digest.eml", mime="message/rfc822")
