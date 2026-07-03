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

import os
import sys
from datetime import datetime

from fedwatch import notify, sources, summarize
from fedwatch.classify import DEFAULT_WATCHLIST, Classifier, sort_by_priority
from fedwatch.relevance import filter_relevant


def main() -> int:
    webhook = os.environ.get("TEAMS_WEBHOOK_URL", "")
    slack = os.environ.get("SLACK_WEBHOOK_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not webhook and not slack and not smtp_host:
        print("SKIPPED: no TEAMS_WEBHOOK_URL or SMTP_HOST secret configured.")
        return 0

    items, errors, used_sample = sources.fetch_all(days_back=7, watchlist=DEFAULT_WATCHLIST)
    if used_sample:
        print("No live feeds reachable; skipping digest.")
        for err in errors:
            print(f"  fetch error: {err}")
        return 0

    items, _ = filter_relevant(items)
    items = sort_by_priority(Classifier(watchlist=DEFAULT_WATCHLIST).classify_all(items))
    summary, engine = summarize.generate_summary(items, "Executive summary")
    title = f"FedWatch Weekly - week of {datetime.now().strftime('%B %d, %Y')}"
    print(f"Summary generated ({engine} engine, {len(items)} items).")

    app_url = os.environ.get("FEDWATCH_APP_URL", "")
    if webhook:
        notify.send_teams_summary(webhook, summary, title=title, app_url=app_url)
        print("Teams: weekly digest posted.")
    if slack:
        notify.send_slack(slack, summary, title=title)
        print("Slack: weekly digest posted.")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
