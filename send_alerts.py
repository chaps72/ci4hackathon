"""Standalone alert sender for scheduled runs (cron / GitHub Actions).

Fetches federal sources, keeps research-relevant items, classifies them, and
sends anything at or above ALERT_MIN_LEVEL that hasn't been alerted before
to a Teams channel and/or email list.

Environment variables:
    TEAMS_WEBHOOK_URL   Teams incoming-webhook URL (optional)
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    ALERT_EMAIL_FROM, ALERT_EMAIL_TO          (all optional, enable email)
    ALERT_MIN_LEVEL     CRITICAL (default) or HIGH
    SEEN_FILE           dedupe state path (default .fedwatch_seen.json)

Usage:  python send_alerts.py
"""

import json
import os
import sys

from fedwatch import notify, sources
from fedwatch.classify import DEFAULT_WATCHLIST, LEVELS, Classifier, sort_by_priority
from fedwatch.deadlines import with_deadlines
from fedwatch.relevance import filter_relevant


def main() -> int:
    min_level = os.environ.get("ALERT_MIN_LEVEL", "CRITICAL").upper()
    seen_file = os.environ.get("SEEN_FILE", ".fedwatch_seen.json")
    webhook = os.environ.get("TEAMS_WEBHOOK_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")

    watchlist = [w.strip() for w in os.environ.get(
        "ALERT_WATCHLIST", ",".join(DEFAULT_WATCHLIST)).split(",") if w.strip()]

    items, errors, used_sample = sources.fetch_all(days_back=7, watchlist=watchlist)
    if used_sample:
        print("No live feeds reachable; not alerting on sample data.")
        for err in errors:
            print(f"  fetch error: {err}")
        return 0

    items, _ = filter_relevant(items)
    items = Classifier(watchlist=watchlist).classify_all(items)
    urgent = [i for i in items if LEVELS.index(i["level"]) <= LEVELS.index(min_level)]

    try:
        with open(seen_file) as f:
            seen = set(json.load(f))
    except (FileNotFoundError, ValueError):
        seen = set()

    app_url = os.environ.get("FEDWATCH_APP_URL", "")

    # Deadline reminders at 14 and 3 days out (deduped per item+milestone).
    reminders = [i for i in with_deadlines(items)
                 if i["days_left"] in (14, 3)
                 and f"dl-{i['id']}-{i['days_left']}" not in seen]
    if reminders and webhook:
        notify.send_teams(
            webhook,
            [{**r, "title": f"Due {r['deadline']} ({r['days_left']}d): {r['title']}"} for r in reminders],
            title=f"⏰ {len(reminders)} comment/response deadline(s) approaching",
            app_url=app_url,
        )
        seen.update(f"dl-{i['id']}-{i['days_left']}" for i in reminders)
        print(f"Teams: sent {len(reminders)} deadline reminder(s).")

    new = sort_by_priority([i for i in urgent if i["id"] not in seen])
    if not new:
        with open(seen_file, "w") as f:
            json.dump(sorted(seen), f)
        print(f"No new {min_level}+ items ({len(urgent)} already alerted).")
        return 0

    title = f"🔴 {len(new)} new {min_level.lower()}+ federal research update(s)"
    sent_somewhere = False
    if webhook:
        notify.send_teams(webhook, new, title, app_url=app_url)
        print(f"Teams: sent {len(new)} item(s).")
        sent_somewhere = True
    if smtp_host:
        notify.send_email(
            smtp_host,
            int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USERNAME", ""),
            os.environ.get("SMTP_PASSWORD", ""),
            os.environ.get("ALERT_EMAIL_FROM", "fedwatch@example.edu"),
            os.environ.get("ALERT_EMAIL_TO", ""),
            new, title=title,
        )
        print(f"Email: sent {len(new)} item(s) to {os.environ.get('ALERT_EMAIL_TO', '')}.")
        sent_somewhere = True

    if not sent_somewhere:
        print("WARNING: no TEAMS_WEBHOOK_URL or SMTP_HOST configured; nothing sent.")
        return 1

    seen.update(i["id"] for i in new)
    with open(seen_file, "w") as f:
        json.dump(sorted(seen), f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
