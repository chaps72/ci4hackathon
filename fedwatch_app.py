"""FedWatch - internal awareness dashboard for federal research updates.

Run with:  streamlit run fedwatch_app.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from fedwatch import emailer, sources, summarize
from fedwatch.classify import (
    LEVELS, LEVEL_DESCRIPTIONS, LEVEL_EMOJI, Classifier, level_counts, sort_by_priority,
)

st.set_page_config(page_title="FedWatch - Federal Research Updates", page_icon="🏛️", layout="wide")

# ---------- Session state ----------
if "watchlist" not in st.session_state:
    st.session_state.watchlist = ["indirect cost", "salary cap", "public access"]
if "feed_items" not in st.session_state:
    st.session_state.feed_items = []
    st.session_state.fetch_errors = []
    st.session_state.used_sample = False
    st.session_state.last_fetch = None
if "read_ids" not in st.session_state:
    st.session_state.read_ids = set()


def refresh(days_back: int, grants_keyword: str):
    with st.spinner("Fetching federal sources..."):
        items, errors, used_sample = sources.fetch_all(days_back=days_back, grants_keyword=grants_keyword)
    classifier = Classifier(watchlist=st.session_state.watchlist)
    st.session_state.feed_items = classifier.classify_all(items)
    st.session_state.fetch_errors = errors
    st.session_state.used_sample = used_sample
    st.session_state.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------- Sidebar ----------
with st.sidebar:
    st.title("🏛️ FedWatch")
    st.caption("Internal awareness of federal research policy & funding updates")

    days_back = st.slider("Look back (days)", 3, 60, 14)
    grants_keyword = st.text_input("Grants.gov keyword", value="research")
    if st.button("🔄 Refresh feeds", use_container_width=True, type="primary"):
        refresh(days_back, grants_keyword)

    st.divider()
    st.subheader("Watchlist keywords")
    st.caption("Any hit bumps an item to at least HIGH and flags it for the team.")
    watchlist_text = st.text_area(
        "One keyword per line", value="\n".join(st.session_state.watchlist), height=110,
        label_visibility="collapsed",
    )
    new_watchlist = [w.strip() for w in watchlist_text.splitlines() if w.strip()]
    if new_watchlist != st.session_state.watchlist:
        st.session_state.watchlist = new_watchlist
        if st.session_state.feed_items:
            classifier = Classifier(watchlist=new_watchlist)
            st.session_state.feed_items = classifier.classify_all(st.session_state.feed_items)

    st.divider()
    with st.expander("Criticality levels"):
        for lvl in LEVELS:
            st.markdown(f"{LEVEL_EMOJI[lvl]} **{lvl.title()}** - {LEVEL_DESCRIPTIONS[lvl]}")

# First load
if not st.session_state.feed_items:
    refresh(days_back, grants_keyword)

items = st.session_state.feed_items
counts = level_counts(items)

# ---------- Header / notification banner ----------
st.title("Federal Research Updates")
meta = f"Last refreshed {st.session_state.last_fetch}"
if st.session_state.used_sample:
    meta += " - **showing bundled sample data** (live feeds unreachable from this environment)"
st.caption(meta)

if st.session_state.fetch_errors and not st.session_state.used_sample:
    with st.expander(f"⚠️ {len(st.session_state.fetch_errors)} source(s) failed to load"):
        for err in st.session_state.fetch_errors:
            st.text(err)

c1, c2, c3, c4 = st.columns(4)
for col, lvl in zip((c1, c2, c3, c4), LEVELS):
    col.metric(f"{LEVEL_EMOJI[lvl]} {lvl.title()}", counts.get(lvl, 0))

unread_urgent = [i for i in items if i["level"] in ("CRITICAL", "HIGH") and i["id"] not in st.session_state.read_ids]
if unread_urgent:
    st.error(f"🔔 {len(unread_urgent)} unread critical/high-priority update(s) need attention.")
watch_flagged = [i for i in items if i.get("watchlist_hits")]
if watch_flagged:
    st.warning(f"👁️ {len(watch_flagged)} item(s) match your watchlist: "
               + "; ".join(sorted({w for i in watch_flagged for w in i['watchlist_hits']})))

tab_feed, tab_summary, tab_email = st.tabs(["📋 Notification feed", "📝 Summaries", "✉️ Email digest"])

# ---------- Tab 1: Feed ----------
with tab_feed:
    f1, f2, f3 = st.columns(3)
    sel_levels = f1.multiselect("Level", LEVELS, default=LEVELS)
    agencies = sorted({i.get("agency", "Unknown") for i in items})
    sel_agencies = f2.multiselect("Agency", agencies, default=[])
    srcs = sorted({i.get("source", "") for i in items})
    sel_sources = f3.multiselect("Source", srcs, default=[])
    only_unread = st.checkbox("Unread only")

    filtered = [
        i for i in items
        if i["level"] in sel_levels
        and (not sel_agencies or i.get("agency") in sel_agencies)
        and (not sel_sources or i.get("source") in sel_sources)
        and (not only_unread or i["id"] not in st.session_state.read_ids)
    ]
    filtered = sort_by_priority(filtered)

    bcol1, bcol2 = st.columns([1, 5])
    if bcol1.button("Mark all read"):
        st.session_state.read_ids.update(i["id"] for i in filtered)
        st.rerun()
    bcol2.caption(f"{len(filtered)} item(s)")

    for it in filtered:
        unread = it["id"] not in st.session_state.read_ids
        marker = "🔵 " if unread else ""
        label = (f"{marker}{LEVEL_EMOJI[it['level']]} [{it['level']}] {it.get('date', '')} - "
                 f"{it.get('title', '')[:110]}")
        with st.expander(label):
            st.markdown(f"**{it.get('title', '')}**")
            st.caption(f"{it.get('agency', '')} · {it.get('source', '')} · {it.get('type', '')} · {it.get('date', '')}")
            if it.get("summary"):
                st.write(it["summary"])
            if it.get("matched_keywords"):
                st.caption("Matched keywords: " + ", ".join(sorted(set(it["matched_keywords"]))))
            if it.get("watchlist_hits"):
                st.caption("👁️ Watchlist: " + ", ".join(it["watchlist_hits"]))
            lc1, lc2 = st.columns([1, 4])
            if unread and lc1.button("Mark read", key=f"read-{it['id']}"):
                st.session_state.read_ids.add(it["id"])
                st.rerun()
            if it.get("url"):
                lc2.markdown(f"[Open source ↗]({it['url']})")

    if filtered:
        st.divider()
        df = pd.DataFrame(filtered)[["level", "date", "agency", "source", "title", "url"]]
        st.download_button("⬇️ Export filtered items (CSV)", df.to_csv(index=False),
                           file_name="fedwatch_items.csv", mime="text/csv")

# ---------- Tab 2: Summaries ----------
with tab_summary:
    st.subheader("Generate a summary")
    engine_note = ("🤖 Claude API connected - AI-written summaries enabled."
                   if summarize.claude_available()
                   else "ℹ️ No ANTHROPIC_API_KEY set - using the built-in template engine. "
                        "Set the key for AI-written summaries.")
    st.caption(engine_note)

    s1, s2 = st.columns(2)
    style = s1.selectbox("Summary type", list(summarize.SUMMARY_STYLES.keys()))
    min_level = s2.selectbox("Include items at or above", LEVELS, index=3)
    extra = st.text_input("Extra instructions (optional)",
                          placeholder="e.g., emphasize impacts on clinical trials")

    eligible = [i for i in items if LEVELS.index(i["level"]) <= LEVELS.index(min_level)]
    st.caption(f"{len(eligible)} item(s) will be summarized.")

    if st.button("Generate summary", type="primary"):
        with st.spinner("Writing summary..."):
            text, engine = summarize.generate_summary(sort_by_priority(eligible), style, extra)
        st.session_state.last_summary = text
        st.session_state.last_summary_engine = engine
        st.session_state.last_summary_items = eligible

    if st.session_state.get("last_summary"):
        st.divider()
        st.markdown(st.session_state.last_summary)
        st.caption(f"Engine: {'Claude (' + summarize.MODEL + ')' if st.session_state.last_summary_engine == 'claude' else 'template'}")
        st.download_button("⬇️ Download summary (Markdown)", st.session_state.last_summary,
                           file_name="fedwatch_summary.md", mime="text/markdown")

# ---------- Tab 3: Email digest ----------
with tab_email:
    st.subheader("Build an email-safe digest")
    st.caption(
        "Output is sanitized for sending: all feed content is HTML-escaped, links are limited to "
        "http(s) sources, inline styles only - no scripts, external images, or tracking pixels."
    )
    e1, e2 = st.columns(2)
    email_title = e1.text_input("Subject / title", value="Federal Research Update - "
                                + datetime.now().strftime("%b %d, %Y"))
    email_min_level = e2.selectbox("Include items at or above", LEVELS, index=2, key="email-level")
    include_summary = st.checkbox("Include the generated summary at the top",
                                  value=bool(st.session_state.get("last_summary")))
    e3, e4 = st.columns(2)
    sender = e3.text_input("From", value="fedwatch@your-institution.edu")
    recipients = e4.text_input("To", value="research-team@your-institution.edu")

    email_items = sort_by_priority(
        [i for i in items if LEVELS.index(i["level"]) <= LEVELS.index(email_min_level)]
    )
    summary_for_email = st.session_state.get("last_summary", "") if include_summary else ""

    if st.button("Build digest", type="primary"):
        st.session_state.email_html = emailer.build_html(email_items, summary_for_email, email_title)
        st.session_state.email_text = emailer.build_plain_text(email_items, summary_for_email, email_title)
        st.session_state.email_eml = emailer.build_eml(email_items, summary_for_email,
                                                       email_title, sender, recipients)

    if st.session_state.get("email_html"):
        st.divider()
        st.markdown("**Preview**")
        st.components.v1.html(st.session_state.email_html, height=500, scrolling=True)
        d1, d2, d3 = st.columns(3)
        d1.download_button("⬇️ HTML", st.session_state.email_html,
                           file_name="fedwatch_digest.html", mime="text/html")
        d2.download_button("⬇️ Plain text", st.session_state.email_text,
                           file_name="fedwatch_digest.txt", mime="text/plain")
        d3.download_button("⬇️ .eml (open in mail client)", st.session_state.email_eml,
                           file_name="fedwatch_digest.eml", mime="message/rfc822")
