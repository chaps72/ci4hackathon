"""Weekly executive digest for scheduled runs (Friday afternoons).

Fetches the week's research policy updates, generates an executive summary
(Claude when ANTHROPIC_API_KEY is set, template otherwise), and posts it to
Teams and/or email.

Environment variables:
    TEAMS_WEBHOOK_URL, FEDWATCH_APP_URL, ANTHROPIC_API_KEY (optional)
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    ALERT_EMAIL_FROM, ALERT_EMAIL_TO          (all optional, enable email)

Usage:  python send_digest.py
"""

import json
import os
import sys
from datetime import datetime

from fedwatch import emailer, notify, sources, summarize
from fedwatch.classify import DEFAULT_WATCHLIST, Classifier, sort_by_priority
from fedwatch.relevance import filter_relevant




def _nih_focused(items: list) -> list:
    """Default digest scope: NIH first.

    Keeps NIH/HHS research actions, NIH Guide/Nexus notices, watchlist and
    tracked items, and OMB/EOP actions (already gated to research-touching).
    Set FEDWATCH_FOCUS=all to widen to the full portfolio (NSF/DOE/DOD/...).
    """
    if os.environ.get("FEDWATCH_FOCUS", "nih").lower() != "nih":
        return items
    out = []
    for i in items:
        agency = (i.get("agency") or "").lower()
        source = i.get("source") or ""
        text = f"{i.get('title', '')} {i.get('summary', '')}".lower()
        if (source in ("NIH Guide", "NIH Nexus", "OMB Memoranda")
                or "institutes of health" in agency
                or "health and human services" in agency
                or "management and budget" in agency
                or "executive office" in agency
                or "nih" in text
                or i.get("watchlist_targeted") or i.get("watchlist_hits")
                or i.get("type") == "Tracked Notice"):
            out.append(i)
    return out

def _scheduled_run_guards() -> str:
    """Reason to skip a scheduled firing, or '' to proceed.

    Two crons fire (21:00 & 22:00 UTC); across DST at least one lands at or
    after 5pm New York. GitHub can delay scheduled runs by an hour or more,
    so the window is "5pm ET or later" (never earlier) rather than an exact
    hour - a once-per-day marker (see main) stops the twin crons from
    double-posting. Manual runs (workflow_dispatch) bypass all guards.
    """
    if os.environ.get("GITHUB_EVENT_NAME", "") != "schedule":
        return ""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fedwatch.holidays import is_us_federal_holiday

    now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return "weekend"
    if is_us_federal_holiday(now_et.date()):
        return f"US federal holiday ({now_et:%Y-%m-%d})"
    if now_et.hour < 17:
        return f"before 5pm ET target window ({now_et:%H:%M} ET)"
    return ""


def main() -> int:
    skip = _scheduled_run_guards()
    if skip:
        print(f"SKIPPED scheduled run: {skip}.")
        return 0
    webhook = os.environ.get("TEAMS_WEBHOOK_URL", "")
    slack = os.environ.get("SLACK_WEBHOOK_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not webhook and not slack and not smtp_host:
        print("SKIPPED: no TEAMS_WEBHOOK_URL or SMTP_HOST secret configured.")
        return 0

    # Cross-day dedupe + once-per-day guard. Loaded up front so a delayed
    # twin cron (or a re-fire) exits fast without spending API calls.
    from zoneinfo import ZoneInfo
    seen_file = os.environ.get("DIGEST_SEEN_FILE", ".fedwatch_digest_seen.json")
    try:
        with open(seen_file) as f:
            seen = set(json.load(f))
    except (FileNotFoundError, ValueError):
        seen = set()
    et_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    sent_marker = f"sent:{et_date}"
    if os.environ.get("GITHUB_EVENT_NAME", "") == "schedule" and sent_marker in seen:
        print(f"A digest already went out today ({et_date}); skipping duplicate cron firing.")
        return 0

    days_back = int(os.environ.get("DIGEST_DAYS_BACK", "7"))
    items, errors, used_sample = sources.fetch_all(
        days_back=days_back, watchlist=DEFAULT_WATCHLIST,
        include_funding=True)  # standing spec: new NIH grant opportunities belong in the digest
    if used_sample:
        print("No live feeds reachable; skipping digest.")
        for err in errors:
            print(f"  fetch error: {err}")
        return 0

    items, _ = filter_relevant(items)
    items = _nih_focused(Classifier(watchlist=DEFAULT_WATCHLIST).classify_all(items))
    if summarize.claude_available():
        # AI relevance judgment per item (same brief as the dashboard).
        items = [i for i in summarize.ai_classify(items) if i.get("relevant", True)]
    items = sort_by_priority(items)
    # Agent step: assess how each item affects Emory research (grounded in
    # Emory's research profile). No-op without an API key.
    items = summarize.analyze_emory_impact(items)

    # Never repeat an item across daily digests (seen-state loaded up top).
    items = [i for i in items if i["id"] not in seen]
    if not items:
        print("Quiet window - no new relevant items; nothing to send.")
        return 0
    summary, engine = summarize.generate_summary(items, "Executive summary")
    cadence = "Daily" if days_back <= 3 else "Weekly"
    title = f"FedWatch {cadence} - {datetime.now().strftime('%B %d, %Y')}"
    print(f"Summary generated ({engine} engine, {len(items)} items).")

    # Publish a styled HTML page (GitHub Pages) and link to it from Slack/Teams.
    import pathlib
    date_str = datetime.now().strftime("%Y-%m-%d")
    page_url = os.environ.get("FEDWATCH_APP_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        page_url = f"https://{owner}.github.io/{name}/digests/{date_str}.html"
    try:
        html = emailer.build_html(items, summary, title)
        ddir = pathlib.Path("docs/digests")
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / f"{date_str}.html").write_text(html, encoding="utf-8")
        dates = sorted({p.stem for p in ddir.glob("*.html") if p.stem[:4].isdigit()})
        pathlib.Path("docs/index.html").write_text(
            emailer.build_archive_index(dates), encoding="utf-8")
        print(f"Digest page written for {date_str}; archive index updated ({len(dates)} total).")
    except Exception as exc:  # noqa: BLE001 - page is a bonus, never block delivery
        print(f"Page write failed ({exc}); sending without link.")

    app_url = page_url
    if webhook:
        notify.send_teams_summary(webhook, summary, title=title, app_url=app_url)
        print(f"Teams: {cadence.lower()} digest posted.")
    if slack:
        notify.send_slack(slack, summary, title=title, link_url=page_url)
        print(f"Slack: {cadence.lower()} digest posted.")
    if smtp_host:
        notify.send_email(
            smtp_host,
            int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USERNAME", ""),
            os.environ.get("SMTP_PASSWORD", ""),
            os.environ.get("ALERT_EMAIL_FROM", "fedwatch@example.edu"),
            os.environ.get("ALERT_EMAIL_TO", ""),
            items, summary_md=summary, title=title,
        )
        print("Email: weekly digest sent.")

    seen.update(i["id"] for i in items)
    seen.add(sent_marker)  # once-per-day guard for the twin crons
    with open(seen_file, "w") as f:
        json.dump(sorted(seen), f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
