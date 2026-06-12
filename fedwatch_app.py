"""FedWatch - internal awareness dashboard for federal research updates.

Run with:  streamlit run fedwatch_app.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

import os

from fedwatch import emailer, notify, sources, summarize
from fedwatch.classify import (
    LEVELS, LEVEL_DESCRIPTIONS, LEVEL_EMOJI, Classifier, level_counts, sort_by_priority,
)
from fedwatch.relevance import filter_relevant

st.set_page_config(page_title="FedWatch - Federal Research Updates", page_icon="🏛️", layout="wide")

# ---------- Emory brand styling ----------
EMORY_BLUE = "#012169"
EMORY_GOLD = "#f2a900"
EMORY_LIGHT_BLUE = "#007dba"

st.markdown(f"""<style>
h1, h2, h3 {{ color: {EMORY_BLUE} !important; font-family: Georgia, 'Times New Roman', serif; }}
[data-testid="stSidebar"] {{ background: #f7f8fb; border-right: 1px solid #e3e7ee; }}
[data-testid="stSidebar"] h1 {{ color: {EMORY_BLUE} !important; font-size: 1.5rem; }}
[data-testid="stExpander"] {{
    border: 1px solid #e3e7ee; border-radius: 10px; background: #ffffff;
    margin-bottom: 6px; box-shadow: 0 1px 2px rgba(1,33,105,0.04);
}}
[data-testid="stExpander"] summary {{ font-size: 0.92rem; }}
[data-testid="stExpander"] summary:hover {{ color: {EMORY_LIGHT_BLUE}; }}
.stButton button[kind="primary"], .stDownloadButton button {{
    background-color: {EMORY_BLUE}; color: #ffffff; border: none; border-radius: 6px;
}}
.stButton button[kind="primary"]:hover, .stDownloadButton button:hover {{
    background-color: {EMORY_LIGHT_BLUE}; color: #ffffff;
}}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 2px solid #e3e7ee; }}
.stTabs [aria-selected="true"] {{ color: {EMORY_BLUE} !important; font-weight: 600; }}
a {{ color: {EMORY_LIGHT_BLUE}; }}
.fedwatch-header {{
    background: linear-gradient(135deg, {EMORY_BLUE} 0%, #02297f 100%);
    border-bottom: 4px solid {EMORY_GOLD};
    border-radius: 10px; padding: 16px 24px 12px 24px; margin-bottom: 16px;
}}
.fedwatch-header h1 {{ color: #ffffff !important; margin: 0; font-size: 1.6rem;
    font-family: Georgia, 'Times New Roman', serif; }}
.fedwatch-header p {{ color: #c8d3ea; margin: 4px 0 0 0; font-size: 0.78rem; }}
.fw-metric {{
    border: 1px solid #e3e7ee; border-top: 4px solid {EMORY_BLUE};
    border-radius: 10px; padding: 10px 16px 12px 16px; background: #ffffff;
    box-shadow: 0 1px 2px rgba(1,33,105,0.04);
}}
.fw-metric .num {{ font: 700 1.7rem Georgia, serif; color: {EMORY_BLUE}; line-height: 1.2; }}
.fw-metric .lab {{ font-size: 0.72rem; color: #6d6e71; text-transform: uppercase;
    letter-spacing: 0.07em; }}
</style>""", unsafe_allow_html=True)

# Built-in watched terms: dedicated 90-day Federal Register search, never
# filtered out, rank at least HIGH. (Formerly a sidebar setting.)
DEFAULT_WATCHLIST = ["indirect cost", "salary cap", "grant cap", "pi cap",
                     "per principal investigator"]

# ---------- Session state ----------
if "feed_items" not in st.session_state:
    st.session_state.feed_items = []
    st.session_state.fetch_errors = []
    st.session_state.used_sample = False
    st.session_state.last_fetch = None
    st.session_state.dropped_count = 0
if "read_ids" not in st.session_state:
    st.session_state.read_ids = set()
if "alerted_ids" not in st.session_state:
    st.session_state.alerted_ids = set()


def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, default)


def refresh(days_back: int, grants_keyword: str, research_only: bool = True,
            include_funding: bool = False, include_news: bool = False):
    with st.spinner("Fetching federal sources..."):
        items, errors, used_sample = sources.fetch_all(
            days_back=days_back, grants_keyword=grants_keyword,
            include_funding=include_funding, include_news=include_news,
            watchlist=DEFAULT_WATCHLIST)
    if research_only:
        items, dropped = filter_relevant(items)
        st.session_state.dropped_count = len(dropped)
    else:
        st.session_state.dropped_count = 0
    classifier = Classifier(watchlist=DEFAULT_WATCHLIST)
    classified = classifier.classify_all(items)
    if st.session_state.get("ai_levels", True) and summarize.claude_available():
        try:
            with st.spinner("AI-refining criticality levels..."):
                classified = summarize.ai_classify(classified)
            irrelevant = [i for i in classified if i.get("relevant") is False]
            if irrelevant:
                st.session_state.dropped_count += len(irrelevant)
                classified = [i for i in classified if i.get("relevant") is not False]
        except Exception as exc:  # noqa: BLE001 - keyword levels still stand
            st.warning(f"AI classification unavailable, using keyword levels: {exc}")
    st.session_state.feed_items = classified
    st.session_state.fetch_errors = errors
    st.session_state.used_sample = used_sample
    st.session_state.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Auto-alert new critical items to Teams when enabled and configured.
    webhook = _secret("TEAMS_WEBHOOK_URL")
    if st.session_state.get("auto_alert") and webhook and not used_sample:
        new_crit = [i for i in st.session_state.feed_items
                    if i["level"] == "CRITICAL" and i["id"] not in st.session_state.alerted_ids]
        if new_crit:
            try:
                notify.send_teams(webhook, new_crit, app_url=_secret("FEDWATCH_APP_URL"))
                st.session_state.alerted_ids.update(i["id"] for i in new_crit)
                st.toast(f"Sent {len(new_crit)} critical alert(s) to Teams")
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Teams alert failed: {exc}")


# ---------- Sidebar ----------
with st.sidebar:
    st.title("FedWatch")
    st.caption("Federal research policy awareness · Office of the SVPR")

    with st.expander("Feed settings"):
        days_back = st.slider("Look back (days)", 3, 60, 14)
        research_only = st.checkbox(
            "Research items only", value=True,
            help="Drops non-research items (e.g., Medicare/Medicaid rules, child support "
                 "program notices) that match federal feeds on words like 'funding' or 'grants'.",
        )
        include_funding = st.checkbox(
            "Include funding opportunities", value=False,
            help="Off by default: focus on research policy and government affairs. Turn on "
                 "to also pull Grants.gov and NIH funding opportunity feeds.",
        )
        include_news = st.checkbox(
            "Include agency press releases", value=False,
            help="NSF News feed: podcasts, discovery stories, award announcements. "
                 "Off by default - not government-affairs signal.",
        )
        grants_keyword = st.text_input("Grants.gov keyword", value="research",
                                       disabled=not include_funding)
        if summarize.claude_available():
            st.checkbox("AI criticality levels (Claude)", value=True, key="ai_levels",
                        help="Claude reads each item and assigns the level - far more accurate "
                             "than keyword matching. Applied on refresh.")
    if st.button("Refresh feeds", use_container_width=True, type="primary"):
        refresh(days_back, grants_keyword, research_only, include_funding, include_news)

    st.divider()
    with st.expander("Criticality levels"):
        for lvl in LEVELS:
            st.markdown(f"{LEVEL_EMOJI[lvl]} **{lvl.title()}** - {LEVEL_DESCRIPTIONS[lvl]}")

# First load
if not st.session_state.feed_items:
    refresh(days_back, grants_keyword, research_only, include_funding, include_news)

items = st.session_state.feed_items
counts = level_counts(items)

# ---------- Header / notification banner ----------
import html as _html

meta = f"Last refreshed {st.session_state.last_fetch}"
if st.session_state.used_sample:
    meta += " — showing bundled sample data (live feeds unreachable from this environment)"
if st.session_state.get("dropped_count"):
    meta += f" — {st.session_state.dropped_count} non-research item(s) filtered out"
_src_counts = {}
for _i in st.session_state.feed_items:
    _src_counts[_i.get("source", "?")] = _src_counts.get(_i.get("source", "?"), 0) + 1
if _src_counts:
    meta += " — sources: " + ", ".join(f"{s} ({n})" for s, n in sorted(_src_counts.items()))
st.markdown(
    f'<div class="fedwatch-header"><h1>FedWatch <span style="font-weight:normal;'
    f'font-size:1.05rem;color:#c8d3ea;">| Federal Research Policy Updates</span></h1>'
    f'<p>{_html.escape(meta)}</p></div>',
    unsafe_allow_html=True,
)

if st.session_state.fetch_errors and not st.session_state.used_sample:
    failed_sources = sorted({e.split(":")[0] for e in st.session_state.fetch_errors})
    st.error(
        f"⚠️ **Coverage degraded - {len(failed_sources)} source(s) unreachable: "
        f"{', '.join(failed_sources)}.** Items from these sources are missing from "
        "this feed. Details below."
    )
    with st.expander("Failure details"):
        for err in st.session_state.fetch_errors:
            st.text(err)

LEVEL_ACCENT = {"CRITICAL": "#c0392b", "HIGH": "#d35400",
                "MODERATE": EMORY_GOLD, "INFO": EMORY_LIGHT_BLUE}
LEVEL_BADGE = {"CRITICAL": "red", "HIGH": "orange", "MODERATE": "gray", "INFO": "blue"}


def fmt_date(d: str) -> str:
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%b %d")
    except ValueError:
        return d or "—"


mcols = st.columns(4)
for col, lvl in zip(mcols, LEVELS):
    col.markdown(
        f'<div class="fw-metric" style="border-top-color:{LEVEL_ACCENT[lvl]}">'
        f'<div class="num">{counts.get(lvl, 0)}</div>'
        f'<div class="lab">{lvl.title()}</div></div>',
        unsafe_allow_html=True,
    )
st.write("")

unread_urgent = [i for i in items if i["level"] in ("CRITICAL", "HIGH") and i["id"] not in st.session_state.read_ids]
if unread_urgent:
    st.error(f"{len(unread_urgent)} unread critical/high-priority update(s) need attention.")
watch_flagged = [i for i in items if i.get("watchlist_hits")]
if watch_flagged:
    st.warning(f"Watchlist matches ({len(watch_flagged)}): "
               + "; ".join(sorted({w for i in watch_flagged for w in i['watchlist_hits']})))

tab_feed, tab_summary, tab_email, tab_alerts = st.tabs(
    ["Feed", "Summaries", "Email digest", "Alerts"])

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
        marker = ":blue[●] " if unread else ""
        badge = f":{LEVEL_BADGE[it['level']]}[**{it['level']}**]"
        label = f"{marker}{badge} · {fmt_date(it.get('date', ''))} · {it.get('title', '')[:100]}"
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
        sc1, sc2 = st.columns(2)
        sc1.download_button("⬇️ Download summary (Markdown)", st.session_state.last_summary,
                            file_name="fedwatch_summary.md", mime="text/markdown")
        summary_webhook = _secret("TEAMS_WEBHOOK_URL")
        if sc2.button("📨 Send summary to Teams", disabled=not summary_webhook,
                      help=("Posts this summary to the Teams channel configured via the "
                            "TEAMS_WEBHOOK_URL secret." if summary_webhook else
                            "Set the TEAMS_WEBHOOK_URL secret (or paste a webhook in the "
                            "Alerts tab) to enable.")):
            try:
                notify.send_teams_summary(
                    summary_webhook, st.session_state.last_summary,
                    title=f"Federal Research Update - {style} ({datetime.now().strftime('%b %d, %Y')})",
                    app_url=_secret("FEDWATCH_APP_URL"))
                st.success("Summary posted to Teams.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Teams post failed: {exc}")

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

# ---------- Tab 4: Alerts ----------
with tab_alerts:
    st.subheader("Critical alert notifications")
    st.caption(
        "Push critical/high items to Microsoft Teams or email. For fully automatic alerts "
        "even when the app is closed, the repo includes a GitHub Actions workflow "
        "(`.github/workflows/fedwatch-alerts.yml`) that runs 3x on weekdays - add "
        "`TEAMS_WEBHOOK_URL` (and/or SMTP secrets) under the repo's Settings → Secrets."
    )

    alert_min = st.selectbox("Alert on items at or above", ["CRITICAL", "HIGH"], index=0)
    alert_items = sort_by_priority(
        [i for i in items if LEVELS.index(i["level"]) <= LEVELS.index(alert_min)])
    new_alert_items = [i for i in alert_items if i["id"] not in st.session_state.alerted_ids]
    st.caption(f"{len(alert_items)} matching item(s); {len(new_alert_items)} not yet alerted this session.")

    st.markdown("**Microsoft Teams**")
    webhook_default = _secret("TEAMS_WEBHOOK_URL")
    webhook_url = st.text_input(
        "Incoming webhook URL", value=webhook_default, type="password",
        help="Teams channel → ⋯ → Workflows/Connectors → Incoming Webhook. "
             "Best stored as the TEAMS_WEBHOOK_URL secret instead of pasted here.")
    t1, t2 = st.columns(2)
    if t1.button("Send to Teams now", type="primary", disabled=not webhook_url):
        try:
            notify.send_teams(webhook_url, new_alert_items or alert_items,
                              app_url=_secret("FEDWATCH_APP_URL"))
            sent = new_alert_items or alert_items
            st.session_state.alerted_ids.update(i["id"] for i in sent)
            st.success(f"Sent {len(sent)} item(s) to Teams.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Teams send failed: {exc}")
    t2.checkbox("Auto-send new critical items on every refresh", key="auto_alert",
                disabled=not webhook_url)

    st.divider()
    st.markdown("**Email (SMTP)**")
    smtp_host = _secret("SMTP_HOST")
    if smtp_host:
        st.caption(f"SMTP configured via secrets ({smtp_host}).")
        alert_to = st.text_input("Send to", value=_secret("ALERT_EMAIL_TO"))
        if st.button("Email these items now", disabled=not alert_to):
            try:
                notify.send_email(
                    smtp_host, int(_secret("SMTP_PORT", "587")),
                    _secret("SMTP_USERNAME"), _secret("SMTP_PASSWORD"),
                    _secret("ALERT_EMAIL_FROM", "fedwatch@your-institution.edu"),
                    alert_to, new_alert_items or alert_items,
                    title=f"🔴 {alert_min.title()} federal research updates",
                )
                sent = new_alert_items or alert_items
                st.session_state.alerted_ids.update(i["id"] for i in sent)
                st.success(f"Emailed {len(sent)} item(s) to {alert_to}.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Email send failed: {exc}")
    else:
        st.caption(
            "Not configured. Add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, "
            "ALERT_EMAIL_FROM to the app's secrets to enable direct sending - or use the "
            "Email digest tab to download a .eml and send it from your mail client.")
