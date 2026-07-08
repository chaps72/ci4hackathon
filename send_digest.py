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


def _deadlines_section(items: list, max_items: int = 8) -> str:
    """A compact 'Deadlines & comment opportunities' block from the structured
    Federal Register fields. Lists items with a comment-close/effective date or
    that are open for public comment (proposed rules / RFIs). '' when none."""
    rows = []
    for it in items:
        comment_due = it.get("comment_due")
        effective = it.get("effective_on")
        is_comment = it.get("comment_opportunity")
        if not (comment_due or effective or is_comment):
            continue
        bits = []
        if comment_due:
            bits.append(f"⏰ comment due {comment_due}")
        elif effective:
            bits.append(f"⏰ effective {effective}")
        if is_comment:
            link = it.get("comment_url") or it.get("url") or ""
            bits.append(f"💬 comment{f': {link}' if link else ''}")
        rows.append(f"- {(it.get('title') or '')[:100]} — " + " · ".join(bits))
        if len(rows) >= max_items:
            break
    return "⏰ Deadlines & comment opportunities\n" + "\n".join(rows) if rows else ""


def _mark_updates(items: list, history: list) -> list:
    """Flag items that update something already covered, rather than brand-new
    matter. Signals: a Federal Register 'Correction', or a shared docket with an
    item seen in a prior digest (e.g. a proposed rule later finalized, a comment
    period extended). Sets item['update_note'] on those; leaves genuinely new
    items untouched."""
    # Earliest prior appearance of each docket (history is appended in order).
    by_docket = {}
    for h in history:
        d = h.get("docket")
        if d and d not in by_docket:
            by_docket[d] = h
    for it in items:
        title = (it.get("title") or "").lower()
        if it.get("type") == "Correction" or "correction" in title:
            it["update_note"] = "Correction to a previously published notice."
            continue
        d = it.get("docket")
        prior = by_docket.get(d) if d else None
        if prior and prior.get("id") != it.get("id"):
            first = prior.get("date", "")
            if it.get("type") == "Rule" and prior.get("type") == "Proposed Rule":
                it["update_note"] = f"Finalizes an earlier proposed rule (docket {d}, first seen {first})."
            else:
                it["update_note"] = f"Update to earlier coverage (docket {d}, first seen {first})."
    return items


def _updates_section(items: list, max_items: int = 8) -> str:
    """A compact 'Updates to earlier items' block for anything flagged by
    _mark_updates. '' when there are none."""
    rows = [f"- {(it.get('title') or '')[:100]} — {it['update_note']}"
            for it in items if it.get("update_note")][:max_items]
    return "🔄 Updates to earlier items\n" + "\n".join(rows) if rows else ""


def _prune_history(history: list, days: int = 21) -> list:
    """Keep only history entries within the last `days` (ISO dates sort
    lexically, so a string compare is enough); drop undated entries."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [h for h in history if (h.get("date") or "") >= cutoff]


def _deliver_note(text: str, title: str, webhook: str, slack: str, only: str) -> None:
    """Post a short operational note (quiet-day heartbeat / degraded-mode
    warning) to the same chat channels the digest uses. Email is intentionally
    skipped to avoid inbox noise. Never raises - a note must not break a run."""
    try:
        if slack and only in ("", "slack"):
            notify.send_slack(slack, text, title=title)
        if webhook and only in ("", "teams"):
            notify.send_teams_summary(webhook, text, title=title)
    except Exception as exc:  # noqa: BLE001
        print(f"Note delivery failed ({exc}).")


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
    # Rolling item history (~3 weeks) for trend threading across digests.
    hist_file = os.environ.get("DIGEST_HISTORY_FILE", ".fedwatch_history.json")
    try:
        with open(hist_file) as f:
            history = json.load(f)
        if not isinstance(history, list):
            history = []
    except (FileNotFoundError, ValueError):
        history = []
    et_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    sent_marker = f"sent:{et_date}"
    # DIGEST_FORCE (manual "force" dispatch input) resends today's items even if
    # they already went out - used to test delivery/rendering on demand.
    force = os.environ.get("DIGEST_FORCE", "").lower() in ("1", "true", "yes")
    if force:
        print("DIGEST_FORCE set: bypassing dedupe and once-per-day guard.")
    # DIGEST_ONLY ("slack"/"teams"/"email") limits delivery to one channel -
    # handy for testing a single destination without spamming the others.
    only = os.environ.get("DIGEST_ONLY", "").strip().lower()
    if not force and os.environ.get("GITHUB_EVENT_NAME", "") == "schedule" and sent_marker in seen:
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

    # Never repeat an item across daily digests (seen-state loaded up top);
    # a forced test run resends regardless.
    if not force:
        items = [i for i in items if i["id"] not in seen]
    if not items:
        print("Quiet window - no new relevant items; nothing to send.")
        # Heartbeat: a quiet day should look different from a broken run, so
        # post a one-line "ran, nothing new" note (real runs only, once per day).
        if not force:
            _deliver_note(
                f"✅ FedWatch ran — no new federal research-policy items today ({et_date} ET).",
                title=f"FedWatch — all quiet ({et_date})",
                webhook=webhook, slack=slack, only=only)
            seen.add(sent_marker)
            with open(seen_file, "w") as f:
                json.dump(sorted(seen), f)
        return 0
    # Flag items that update earlier coverage (corrections, shared FR docket)
    # before rendering, so both the page and the message can mark them.
    items = _mark_updates(items, history)
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

    # Bottom-of-message sections, in order: deadlines/comment opportunities
    # (from FR structured fields), a trend note (today vs the rolling history),
    # then the government-affairs roundup.
    updates_md = _updates_section(items)
    deadlines_md = _deadlines_section(items)
    trend = summarize.trend_note(items, history)  # `history` is the log BEFORE today
    trend_md = f"📈 Trend watch\n{trend}" if trend else ""
    brief = summarize.govt_affairs_brief(items)
    gov_md = f"🏛️ Government affairs\n{brief}" if brief else ""
    extra_md = "\n\n".join(s for s in (updates_md, deadlines_md, trend_md, gov_md) if s)

    if webhook and only in ("", "teams"):
        notify.send_teams_summary(webhook, summary, title=title, extra_md=extra_md)
        print(f"Teams: {cadence.lower()} digest posted.")
    if slack and only in ("", "slack"):
        notify.send_slack(slack, summary, title=title, extra_md=extra_md)
        print(f"Slack: {cadence.lower()} digest posted.")
    if smtp_host and only in ("", "email"):
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

    # Degraded-mode warning: the digest still went out, but if Claude was
    # configured yet unreachable (credits/outage) the analysis fell back to a
    # plain template - flag that so it never silently degrades.
    if engine == "template" and summarize.claude_available():
        _deliver_note(
            "⚠️ FedWatch: AI analysis was unavailable this run (likely an Anthropic "
            "API error - check credits). The digest above is a basic template; the "
            "executive summary, Emory-impact, and government-affairs sections are "
            "degraded until it is restored.",
            title="FedWatch - AI analysis unavailable",
            webhook=webhook, slack=slack, only=only)
        print("Degraded-mode warning posted.")

    # A forced test run must NOT touch the dedupe state: writing the sent
    # marker (or item ids) would make the real scheduled digest think it
    # already went out and skip. Only real runs persist seen-state.
    if not force:
        seen.update(i["id"] for i in items)
        seen.add(sent_marker)  # once-per-day guard for the twin crons
        with open(seen_file, "w") as f:
            json.dump(sorted(seen), f)
        # Append today's items to the rolling history (for trend threading) and
        # prune to the retention window.
        history.extend({
            "id": i.get("id"), "date": i.get("date"), "agency": i.get("agency"),
            "title": i.get("title"), "level": i.get("level"),
            "docket": i.get("docket"), "type": i.get("type"),
        } for i in items)
        with open(hist_file, "w") as f:
            json.dump(_prune_history(history), f)
    else:
        print("Forced test run: not updating dedupe/seen-state.")
    return 0


def _run_with_alert() -> int:
    """Run main(); on an unexpected error, post a short failure notice so a
    broken run is never silent, then surface the failure to CI (exit 1)."""
    try:
        return main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        msg = f"⚠️ FedWatch digest failed to run: {type(exc).__name__}: {exc}"
        slack = os.environ.get("SLACK_WEBHOOK_URL", "")
        teams = os.environ.get("TEAMS_WEBHOOK_URL", "")
        try:
            if slack:
                notify.send_slack(slack, msg, title="FedWatch digest error")
            elif teams:
                notify.send_teams_summary(teams, msg, title="FedWatch digest error")
        except Exception:  # noqa: BLE001 - don't mask the original error
            pass
        return 1


if __name__ == "__main__":
    sys.exit(_run_with_alert())
