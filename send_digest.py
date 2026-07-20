"""Daily/weekly digest for scheduled runs.

Fetches recent research policy updates, generates an executive summary
(Claude when ANTHROPIC_API_KEY is set, template otherwise), publishes an
HTML page, and posts to Slack/Teams/email.

Environment variables:
    SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL, ANTHROPIC_API_KEY (optional)
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    ALERT_EMAIL_FROM, ALERT_EMAIL_TO          (all optional, enable email)
    DIGEST_DAYS_BACK, FEDWATCH_FOCUS, DIGEST_FORCE, DIGEST_ONLY

Usage:  python send_digest.py
"""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fedwatch import deadlines, emailer, notify, sources, summarize
from fedwatch.classify import DEFAULT_WATCHLIST, Classifier, sort_by_priority
from fedwatch.relevance import filter_relevant

# Item ids are kept in the dedupe cache this long. The fetch window is a few
# days, so anything older cannot reappear; this keeps the cache from growing
# without bound.
SEEN_RETENTION_DAYS = 45
HISTORY_RETENTION_DAYS = 21


# --------------------------------------------------------------------------
# Guards & scope

def _scheduled_run_guards(now_et=None) -> str:
    """Reason to skip a scheduled firing, or '' to proceed.

    Weekends and US federal holidays are skipped. Off-hour firings are NOT
    skipped - the first cron fires before 5pm on purpose and main() holds
    delivery until exactly 5:00pm ET (see _seconds_until_5pm_et). Manual runs
    (workflow_dispatch) bypass all guards.
    """
    if os.environ.get("GITHUB_EVENT_NAME", "") != "schedule":
        return ""
    from fedwatch.holidays import is_us_federal_holiday

    if now_et is None:
        now_et = datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return "weekend"
    if is_us_federal_holiday(now_et.date()):
        return f"US federal holiday ({now_et:%Y-%m-%d})"
    return ""


def _seconds_until_5pm_et(now_et=None) -> int:
    """Seconds to hold before delivering, so the digest lands AT 5:00pm ET.

    GitHub's cron is best-effort and usually late, so the first cron of the
    day fires early and waits here; a firing already past 5pm returns 0 and
    posts immediately (that's the backup-cron path).
    """
    if now_et is None:
        now_et = datetime.now(ZoneInfo("America/New_York"))
    target = now_et.replace(hour=17, minute=0, second=0, microsecond=0)
    return max(0, int((target - now_et).total_seconds()))


# DOD publishes far more procurement/operations than research; a Defense item
# must show one of these signals to enter the digest (the AI relevance judge
# then screens what remains against the SVPR brief).
_DOD_RESEARCH_SIGNALS = (
    "research", "universit", "grant", "academ", "scienc", "laborator",
    "stem", "basic research", "darpa", "fellowship", "r&d",
)


def _nih_focused(items: list) -> list:
    """Default digest scope: NIH first, plus NSF and research-relevant DOD.

    Keeps NIH/HHS research actions, NIH Guide/Nexus notices, watchlist and
    tracked items, OMB/EOP actions (already gated to research-touching), all
    NSF actions, and DOD/DARPA actions that carry a research signal.
    Set FEDWATCH_FOCUS=all to widen to the full portfolio (DOE/NASA/...).
    """
    if os.environ.get("FEDWATCH_FOCUS", "nih").lower() != "nih":
        return items
    out = []
    for i in items:
        agency = (i.get("agency") or "").lower()
        source = i.get("source") or ""
        text = f"{i.get('title', '')} {i.get('summary', '')}".lower()
        is_dod = ("defense" in agency or "darpa" in agency
                  or "advanced research projects" in agency
                  or any(b in agency for b in ("department of the army",
                                               "department of the navy",
                                               "department of the air force")))
        if (source in ("NIH Guide", "NIH Nexus", "OMB Memoranda")
                or "institutes of health" in agency
                or "health and human services" in agency
                or "management and budget" in agency
                or "executive office" in agency
                or "science foundation" in agency          # NSF: inherently research
                or (is_dod and any(s in text for s in _DOD_RESEARCH_SIGNALS))
                or "nih" in text
                or i.get("watchlist_targeted") or i.get("watchlist_hits")
                or i.get("type") in ("Tracked Notice", "News")):
            out.append(i)
    return out


# --------------------------------------------------------------------------
# State (dedupe cache + rolling history)

def _load_seen(path: str) -> dict:
    """Dedupe cache mapping id/marker -> date first recorded (YYYY-MM-DD).

    Older versions stored a bare list of ids; those migrate to today's date so
    they age out of the cache on schedule.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
    if isinstance(data, list):  # legacy format
        today = datetime.now().strftime("%Y-%m-%d")
        return {k: today for k in data}
    return data if isinstance(data, dict) else {}


def _prune_seen(seen: dict, days: int = SEEN_RETENTION_DAYS) -> dict:
    """Drop entries older than the retention window (ISO dates compare
    lexically). Undated entries are dropped too - they can't age out."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return {k: v for k, v in seen.items() if (v or "") >= cutoff}


def _save_seen(path: str, seen: dict) -> None:
    with open(path, "w") as f:
        json.dump(_prune_seen(seen), f, sort_keys=True)


def _load_history(path: str) -> list:
    try:
        with open(path) as f:
            history = json.load(f)
        return history if isinstance(history, list) else []
    except (FileNotFoundError, ValueError):
        return []


def _prune_history(history: list, days: int = HISTORY_RETENTION_DAYS) -> list:
    """Keep only history entries within the last `days` (ISO dates sort
    lexically, so a string compare is enough); drop undated entries."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [h for h in history if (h.get("date") or "") >= cutoff]


# --------------------------------------------------------------------------
# Pipeline steps

def _gather_items(days_back: int):
    """Fetch, filter to relevance/NIH scope, classify, and analyze. Returns
    the prioritized item list, or None when no live feeds were reachable."""
    items, errors, used_sample = sources.fetch_all(
        days_back=days_back, watchlist=DEFAULT_WATCHLIST,
        include_funding=True)  # standing spec: new NIH grant opportunities belong in the digest
    if used_sample:
        print("No live feeds reachable; skipping digest.")
        for err in errors:
            print(f"  fetch error: {err}")
        return None
    # Press sweep: web-search the research press for actions that never hit
    # the Federal Register (terminations by letter, freezes, shakeups).
    news = summarize.news_sweep(days_back=days_back)
    if news:
        print(f"News sweep: {len(news)} press item(s) found.")
        items.extend(news)
    items, _ = filter_relevant(items)
    items = _nih_focused(Classifier(watchlist=DEFAULT_WATCHLIST).classify_all(items))
    if summarize.claude_available():
        # AI relevance judgment per item (same brief as the dashboard).
        items = [i for i in summarize.ai_classify(items) if i.get("relevant", True)]
    items = sort_by_priority(items)
    # Agent step: assess how each item affects Emory research (grounded in
    # Emory's research profile). No-op without an API key.
    return summarize.analyze_emory_impact(items)


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


def _deadlines_section(items: list, max_items: int = 8) -> str:
    """A compact 'Deadlines & comment opportunities' block. Prefers the
    structured Federal Register fields; falls back to a deadline extracted
    from the notice text for sources without structured dates. '' when none."""
    rows = []
    for it in items:
        comment_due = it.get("comment_due")
        effective = it.get("effective_on")
        is_comment = it.get("comment_opportunity")
        text_deadline = None
        if not (comment_due or effective or is_comment):
            text_deadline = deadlines.extract_deadline(it)
            if not text_deadline:
                continue
        bits = []
        if comment_due:
            bits.append(f"⏰ comment due {comment_due}")
        elif effective:
            bits.append(f"⏰ effective {effective}")
        elif text_deadline:
            bits.append(f"⏰ due {text_deadline}")
        if is_comment:
            link = it.get("comment_url") or it.get("url") or ""
            bits.append(f"💬 comment{f': {link}' if link else ''}")
        rows.append(f"- {(it.get('title') or '')[:100]} — " + " · ".join(bits))
        if len(rows) >= max_items:
            break
    return "⏰ Deadlines & comment opportunities\n" + "\n".join(rows) if rows else ""


def _split_press(items: list) -> tuple[list, list]:
    """Separate press-sweep stories from official register items so the press
    coverage renders as its own section rather than mixed into the item list."""
    press = [i for i in items if i.get("type") == "News"]
    official = [i for i in items if i.get("type") != "News"]
    return official, press


def _press_section(press: list, max_items: int = 5) -> str:
    """A 'From the research press' block: outlet-reported actions (often never
    published in the Federal Register). '' when the sweep found nothing."""
    rows = []
    for it in press[:max_items]:
        line = f"- {(it.get('title') or '')[:120]} — {it.get('agency', '')}"
        if it.get("date"):
            line += f", {it['date']}"
        if it.get("summary"):
            line += f"\n  {it['summary'][:200]}"
        if it.get("url"):
            line += f"\n  {it['url']}"
        rows.append(line)
    return "📰 From the research press\n" + "\n".join(rows) if rows else ""


def _build_sections(items: list, history: list, press: list | None = None) -> str:
    """Bottom-of-message sections, in order: updates to earlier items,
    deadlines/comment opportunities, research-press sweep, trend note,
    government-affairs roundup."""
    updates_md = _updates_section(items)
    deadlines_md = _deadlines_section(items)
    press_md = _press_section(press or [])
    everything = items + (press or [])
    trend = summarize.trend_note(everything, history)  # history is the log BEFORE today
    trend_md = f"📈 Trend watch\n{trend}" if trend else ""
    brief = summarize.govt_affairs_brief(everything)
    gov_md = f"🏛️ Government affairs\n{brief}" if brief else ""
    return "\n\n".join(s for s in (updates_md, deadlines_md, press_md, trend_md, gov_md) if s)


def _publish_page(items: list, summary: str, title: str,
                  press: list | None = None) -> None:
    """Write the styled HTML digest page and refresh the archive index
    (published to GitHub Pages by the workflow). Never blocks delivery."""
    import pathlib
    date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        html = emailer.build_html(items, summary, title, press_items=press)
        ddir = pathlib.Path("docs/digests")
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / f"{date_str}.html").write_text(html, encoding="utf-8")
        dates = sorted({p.stem for p in ddir.glob("*.html") if p.stem[:4].isdigit()})
        pathlib.Path("docs/index.html").write_text(
            emailer.build_archive_index(dates), encoding="utf-8")
        print(f"Digest page written for {date_str}; archive index updated ({len(dates)} total).")
    except Exception as exc:  # noqa: BLE001 - page is a bonus, never block delivery
        print(f"Page write failed ({exc}); sending without link.")


def _deliver_digest(summary: str, extra_md: str, title: str, cadence: str,
                    items: list, webhook: str, slack: str, smtp_host: str,
                    only: str) -> None:
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
        print("Email: digest sent.")


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


def _persist_state(seen_file: str, seen: dict, hist_file: str, history: list,
                   items: list, sent_marker: str, et_date: str) -> None:
    """Record today's items in the dedupe cache and rolling history."""
    for i in items:
        seen[i["id"]] = et_date
    seen[sent_marker] = et_date  # once-per-day guard for the twin crons
    _save_seen(seen_file, seen)
    history.extend({
        "id": i.get("id"), "date": i.get("date"), "agency": i.get("agency"),
        "title": i.get("title"), "level": i.get("level"),
        "docket": i.get("docket"), "type": i.get("type"),
    } for i in items)
    with open(hist_file, "w") as f:
        json.dump(_prune_history(history), f)


# --------------------------------------------------------------------------

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
    seen_file = os.environ.get("DIGEST_SEEN_FILE", ".fedwatch_digest_seen.json")
    seen = _load_seen(seen_file)
    hist_file = os.environ.get("DIGEST_HISTORY_FILE", ".fedwatch_history.json")
    history = _load_history(hist_file)
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

    # Hold until exactly 5:00pm ET (scheduled runs only). The first cron of
    # the day fires early because GitHub's scheduler is usually late; waiting
    # here is what makes delivery land AT 5pm instead of 5:20-6:30.
    if os.environ.get("GITHUB_EVENT_NAME", "") == "schedule":
        wait = _seconds_until_5pm_et()
        if wait > 0:
            import time
            print(f"Holding delivery for {wait // 60}m {wait % 60}s until 5:00pm ET...")
            time.sleep(wait)

    days_back = int(os.environ.get("DIGEST_DAYS_BACK", "7"))
    items = _gather_items(days_back)
    if items is None:
        return 0

    # Never repeat an item across daily digests; a forced test run resends.
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
            print("Quiet-day heartbeat posted.")
            seen[sent_marker] = et_date
            _save_seen(seen_file, seen)
        return 0

    # Flag items that update earlier coverage (corrections, shared FR docket)
    # before rendering, so both the page and the message can mark them.
    items = _mark_updates(items, history)
    official, press = _split_press(items)
    if press:
        print(f"Research press: {len(press)} story(ies) in this digest.")
    summary, engine = summarize.generate_summary(items, "Executive summary")
    cadence = "Daily" if days_back <= 3 else "Weekly"
    title = f"FedWatch {cadence} - {datetime.now().strftime('%B %d, %Y')}"
    print(f"Summary generated ({engine} engine, {len(items)} items).")

    _publish_page(official, summary, title, press=press)
    extra_md = _build_sections(official, history, press=press)
    _deliver_digest(summary, extra_md, title, cadence, items,
                    webhook, slack, smtp_host, only)

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
        _persist_state(seen_file, seen, hist_file, history, items, sent_marker, et_date)
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
