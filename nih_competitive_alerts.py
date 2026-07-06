"""Scheduled competitive-intelligence alerts for cron / GitHub Actions.

Watches PEER institutions for sizeable new NIH awards in the areas Emory cares
about, and posts anything above a dollar threshold to Teams / Slack / email.
De-duplicates against a seen-file so each award is alerted once.

Environment variables:
    PEER_ORGS          Comma-separated institutions to watch
                       (default: Duke, Vanderbilt, Johns Hopkins, Washington
                        University, University of Pittsburgh)
    ALERT_ICS          Comma-separated NIH IC codes to focus on (e.g. "NCI,NIAID");
                       empty = all ICs
    ALERT_TOPIC        Optional research terms to narrow to Emory's focus areas
    ALERT_DAYS         Look-back window in days (default: 7)
    ALERT_MIN_AMOUNT   Minimum award amount to flag (default: 2000000)
    SEEN_FILE          De-dupe state path (default: .nih_competitive_seen.json)
    TEAMS_WEBHOOK_URL, SLACK_WEBHOOK_URL                    (optional)
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    ALERT_EMAIL_FROM, ALERT_EMAIL_TO                        (optional, enable email)

Usage:  python nih_competitive_alerts.py
"""

import json
import os
import sys
from datetime import datetime

from fedwatch import notify, reporter

DEFAULT_PEERS = ["DUKE UNIVERSITY", "VANDERBILT UNIVERSITY",
                 "JOHNS HOPKINS UNIVERSITY", "WASHINGTON UNIVERSITY",
                 "UNIVERSITY OF PITTSBURGH"]


def main() -> int:
    teams = os.environ.get("TEAMS_WEBHOOK_URL", "")
    slack = os.environ.get("SLACK_WEBHOOK_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not (teams or slack or smtp_host):
        print("WARNING: no TEAMS_WEBHOOK_URL, SLACK_WEBHOOK_URL, or SMTP_HOST set; "
              "nothing to send.")
        print("SKIPPED: configure delivery secrets to enable sending.")
        return 0

    peers = [p.strip() for p in os.environ.get(
        "PEER_ORGS", ", ".join(DEFAULT_PEERS)).split(",") if p.strip()]
    ics = [c.strip() for c in os.environ.get("ALERT_ICS", "").split(",") if c.strip()]
    topic = os.environ.get("ALERT_TOPIC", "")
    days = int(os.environ.get("ALERT_DAYS", "7"))
    min_amt = int(os.environ.get("ALERT_MIN_AMOUNT", "2000000"))
    seen_file = os.environ.get("SEEN_FILE", ".nih_competitive_seen.json")

    try:
        seen = set(json.load(open(seen_file)))
    except Exception:  # noqa: BLE001
        seen = set()

    flagged = []
    for org in peers:
        items, err = reporter.fetch_awards(
            org_names=[org], text_query=topic, ic_codes=ics or None,
            days_back=days, limit=500)
        if err:
            print(f"  {org}: fetch error: {err}")
            continue
        for it in items:
            amt = it.get("amount") or 0
            try:
                amt = int(amt)
            except (TypeError, ValueError):
                amt = 0
            if amt >= min_amt and it.get("id") not in seen:
                flagged.append(it)

    if not flagged:
        print("No new competitive awards over the threshold.")
        return 0

    flagged.sort(key=lambda i: int(i.get("amount") or 0), reverse=True)
    lines = []
    for it in flagged:
        lines.append(
            f"- **{reporter.fmt_money(it.get('amount'))}** · {it.get('org', '')} · "
            f"{it.get('ic', '')} {it.get('activity_code', '')} · "
            f"PI: {it.get('pi', '')}  \n  {it.get('title', '')}")
    title = (f"Competitive NIH alert — {len(flagged)} new peer award(s) over "
             f"{reporter.fmt_money(min_amt)} ({datetime.now():%b %d, %Y})")
    body = title + "\n\n" + "\n".join(lines)
    print(body)

    if teams:
        notify.send_teams_summary(teams, body, title=title)
        print("Teams: alert posted.")
    if slack:
        notify.send_slack(slack, body, title=title)
        print("Slack: alert posted.")
    if smtp_host:
        notify.send_email(
            smtp_host, int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USERNAME", ""), os.environ.get("SMTP_PASSWORD", ""),
            os.environ.get("ALERT_EMAIL_FROM", "nih-alerts@example.edu"),
            os.environ.get("ALERT_EMAIL_TO", ""), flagged,
            summary_md=body, title=title)
        print("Email: alert sent.")

    seen.update(it.get("id") for it in flagged)
    try:
        json.dump(sorted(seen), open(seen_file, "w"))
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
