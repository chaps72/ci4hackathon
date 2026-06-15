"""Scheduled NIH RePORTER weekly award report for cron / GitHub Actions.

Pulls the week's newly issued NIH awards for an organization (or topic),
generates an executive summary (Claude when ANTHROPIC_API_KEY is set, template
otherwise), and delivers it to Teams, Slack, and/or email.

Environment variables:
    NIH_ORG            Organization name (default: EMORY UNIVERSITY)
    NIH_TOPIC          Optional research terms to narrow the report
    NIH_DAYS           Look-back window in days (default: 7)
    NIH_IC             Optional comma-separated IC codes (e.g. "NCI,NIAID")
    TEAMS_WEBHOOK_URL  Teams incoming-webhook URL (optional)
    SLACK_WEBHOOK_URL  Slack incoming-webhook URL (optional)
    ANTHROPIC_API_KEY  Optional, enables Claude-written summaries
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    ALERT_EMAIL_FROM, ALERT_EMAIL_TO          (all optional, enable email)

Usage:  python nih_weekly_report.py
"""

import os
import sys
from datetime import datetime

from fedwatch import emailer, notify, reporter, summarize


def main() -> int:
    teams = os.environ.get("TEAMS_WEBHOOK_URL", "")
    slack = os.environ.get("SLACK_WEBHOOK_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not (teams or slack or smtp_host):
        print("WARNING: no TEAMS_WEBHOOK_URL, SLACK_WEBHOOK_URL, or SMTP_HOST "
              "configured; nothing to send.")
        return 1

    org = os.environ.get("NIH_ORG", reporter.DEFAULT_ORG)
    topic = os.environ.get("NIH_TOPIC", "")
    days = int(os.environ.get("NIH_DAYS", "7"))
    ic = [c.strip() for c in os.environ.get("NIH_IC", "").split(",") if c.strip()]

    items, err = reporter.fetch_awards(
        org_names=[org] if org else None, text_query=topic,
        ic_codes=ic or None, days_back=days, limit=500)
    if err:
        print(f"NIH RePORTER unreachable; skipping report. ({err})")
        return 0
    if not items:
        print(f"No NIH awards for '{org}' in the last {days} days; nothing to send.")
        return 0

    agg = reporter.aggregate(items)
    summary, engine = summarize.generate_summary(
        items, style="Executive summary",
        extra_instructions=(
            "These are newly issued NIH research awards. Lead with funding totals "
            "and notable awards, group by theme, name PIs and institutes, and note "
            "the new vs. renewal mix. Do not invent figures."))
    title = f"NIH RePORTER Weekly - {org.title()} - week of {datetime.now().strftime('%B %d, %Y')}"
    header = (f"{agg['count']} new awards · {reporter.fmt_money(agg['total_amount'])} "
              f"total · {len(agg['by_ic'])} institutes\n\n")
    print(f"{title}: {agg['count']} awards, {reporter.fmt_money(agg['total_amount'])} "
          f"({engine} summary).")

    if teams:
        notify.send_teams_summary(teams, header + summary, title=title)
        print("Teams: report posted.")
    if slack:
        notify.send_slack(slack, header + summary, title=title)
        print("Slack: report posted.")
    if smtp_host:
        notify.send_email(
            smtp_host, int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USERNAME", ""), os.environ.get("SMTP_PASSWORD", ""),
            os.environ.get("ALERT_EMAIL_FROM", "nih-report@example.edu"),
            os.environ.get("ALERT_EMAIL_TO", ""),
            items, summary_md=header + summary, title=title)
        print("Email: report sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
