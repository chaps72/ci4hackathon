"""Weekly executive briefing by email — standalone script for cron/Actions.

Pulls the same data as the app's Weekly executive briefing (this week, recent
weeks, and the last three fiscal years), writes an executive summary (Claude
when ANTHROPIC_API_KEY is set, a deterministic template otherwise), builds a
PDF with the key charts, and emails it with the PDF attached.

NOT YET SCHEDULED: the companion workflow (.github/workflows/
nih-exec-briefing.yml) is manual-trigger only until leadership signs off.

Environment variables:
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD   (required)
    EXEC_EMAIL_FROM     sender address (default nih-reporter@emory.edu)
    EXEC_EMAIL_TO       comma-separated recipients (required)
    ANTHROPIC_API_KEY   optional — enables the AI-written summary

Usage:  python nih_exec_briefing_email.py
"""

import io
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage

from fedwatch import reporter, summarize

ORG = reporter.DEFAULT_ORG
NOW = datetime.now()
CURRENT_FY = NOW.year + (1 if NOW.month >= 10 else 0)
FISCAL_MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
                 "Jun", "Jul", "Aug", "Sep"]
NAVY, INK, MUTED = "#012169", "#1d1d1f", "#6e6e73"


def _money_fmt(x, _pos=None):
    return (f"${x/1e6:.1f}M" if x >= 1e6
            else f"${x/1e3:.0f}K" if x >= 1e3 else f"${x:.0f}")


def fiscal_cumulative(items, metric, upto_pos=11):
    buckets = [0] * 12
    for it in items:
        try:
            mo = int((it.get("award_date") or "")[5:7])
        except (ValueError, IndexError):
            continue
        pos = (mo - 10) % 12
        buckets[pos] += (int(it.get("amount") or 0) if metric == "funding" else 1)
    cum, t = [], 0
    for b in buckets:
        t += b
        cum.append(t)
    return cum[:upto_pos + 1]


def build_pdf(week, wk_all, fy_by_year, summary_md) -> bytes:
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.ticker import FuncFormatter

    aw = reporter.aggregate(week)
    af = reporter.aggregate(fy_by_year.get(CURRENT_FY) or [])
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.08, 0.955, "EMORY RESEARCH", color=NAVY, fontsize=11,
                 fontweight="bold")
        fig.text(0.08, 0.928, "Weekly executive briefing", color=INK,
                 fontsize=22, fontweight="bold")
        fig.text(0.08, 0.903, f"Week ending {NOW:%B %d, %Y} · {ORG.title()} · "
                 "NIH RePORTER", color=MUTED, fontsize=9)
        fig.text(0.08, 0.868,
                 f"This week: {aw['count']} new awards · "
                 f"{reporter.fmt_money(aw['total_amount'])}        "
                 f"FY{CURRENT_FY} to date: {af['count']} awards · "
                 f"{reporter.fmt_money(af['total_amount'])}",
                 color=NAVY, fontsize=11, fontweight="bold")
        body = re.sub(r"[*#`>]", "", summary_md or "")
        lines = []
        for para in body.split("\n"):
            lines += (textwrap.wrap(para, width=98) or [""])
        fig.text(0.08, 0.835, "\n".join(lines[:72]), color=INK, fontsize=9.5,
                 va="top")
        plt.axis("off")
        pdf.savefig(fig)
        plt.close(fig)

        def page(draw):
            fig, ax = plt.subplots(figsize=(8.5, 5.6))
            draw(ax)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            ax.tick_params(colors=INK, labelsize=9)
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        wk_f = reporter.by_period(wk_all, "week", "funding")
        if len(wk_f) > 1:
            def _wk(ax):
                ax.bar(list(wk_f), list(wk_f.values()), color=NAVY)
                ax.tick_params(axis="x", rotation=45)
                ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
                ax.set_title("Funding by week — last ~10 weeks", color=NAVY,
                             fontsize=14, fontweight="bold", loc="left", pad=14)
            page(_wk)

        pos_today = (NOW.month - 10) % 12
        pal = [NAVY, "#f2a900", "#8a94ad"]
        if len(fy_by_year) > 1:
            def _pace(ax):
                for ci, y in enumerate(sorted(fy_by_year, reverse=True)):
                    upto = pos_today if y == CURRENT_FY else 11
                    cum = fiscal_cumulative(fy_by_year[y], "funding", upto)
                    ax.plot(FISCAL_MONTHS[:len(cum)], cum, linewidth=2,
                            marker="o", markersize=3, label=f"FY{y}",
                            color=pal[ci % len(pal)])
                ax.yaxis.set_major_formatter(FuncFormatter(_money_fmt))
                ax.legend(fontsize=8, frameon=False)
                ax.set_title("Cumulative funding — this FY vs prior years",
                             color=NAVY, fontsize=14, fontweight="bold",
                             loc="left", pad=14)
            page(_pace)

        agg = reporter.aggregate(fy_by_year.get(CURRENT_FY) or [])
        for title, d in ((f"FY{CURRENT_FY} funding by institute",
                          agg.get("funding_by_ic")),
                         (f"FY{CURRENT_FY} funding by mechanism",
                          agg.get("funding_by_activity"))):
            rows = list((d or {}).items())[:12]
            if not rows:
                continue

            def _cat(ax, rows=rows, title=title):
                ax.barh([k for k, _ in rows][::-1],
                        [v for _, v in rows][::-1], color=NAVY)
                ax.xaxis.set_major_formatter(FuncFormatter(_money_fmt))
                ax.set_title(title, color=NAVY, fontsize=14,
                             fontweight="bold", loc="left", pad=14)
            page(_cat)
    return buf.getvalue()


def main() -> int:
    host = os.environ.get("SMTP_HOST", "")
    to = os.environ.get("EXEC_EMAIL_TO", "")
    if not host or not to:
        print("SMTP_HOST and EXEC_EMAIL_TO are required; nothing sent.")
        return 1

    wk_all, wk_err = reporter.fetch_awards(
        org_names=[ORG], use_award_window=True, days_back=70, limit=2000)
    fy_by_year = {}
    for y in (CURRENT_FY, CURRENT_FY - 1, CURRENT_FY - 2):
        items, err = reporter.fetch_awards(
            org_names=[ORG], use_award_window=False, fiscal_years=[y],
            limit=8000)
        if not err:
            fy_by_year[y] = items
    if wk_err and not fy_by_year:
        print(f"NIH RePORTER unreachable: {wk_err}")
        return 1
    week = [it for it in (wk_all or [])
            if (it.get("award_date") or "") >=
            (NOW - timedelta(days=7)).strftime("%Y-%m-%d")]

    aw = reporter.aggregate(week)
    af = reporter.aggregate(fy_by_year.get(CURRENT_FY) or [])
    if summarize.claude_available():
        facts = ("THIS WEEK:\n" + f"{aw['count']} award notices, "
                 f"{reporter.fmt_money(aw['total_amount'])}.\n\nFY TO DATE:\n"
                 + f"{af['count']} award notices, "
                 f"{reporter.fmt_money(af['total_amount'])}.\n"
                 "Funding by IC: " + ", ".join(
                     f"{k}: {reporter.fmt_money(v)}" for k, v in
                     list((af.get('funding_by_ic') or {}).items())[:10]))
        try:
            summary, _ = summarize.custom_report(
                "Write a tight weekly executive summary of Emory's NIH awards: "
                "this week and fiscal-year-to-date, clarifying how many award "
                "notices are entirely new grants vs renewals/continuations.",
                facts)
        except Exception as exc:  # noqa: BLE001
            summary = f"(AI summary unavailable: {exc})"
    else:
        summary = (f"This week: {aw['count']} NIH award notices totaling "
                   f"{reporter.fmt_money(aw['total_amount'])}. FY{CURRENT_FY} "
                   f"to date: {af['count']} award notices totaling "
                   f"{reporter.fmt_money(af['total_amount'])}. Details and "
                   "charts attached.")

    pdf = build_pdf(week, wk_all or [], fy_by_year, summary)

    msg = EmailMessage()
    msg["Subject"] = (f"NIH weekly executive briefing — {NOW:%b %d, %Y}")
    msg["From"] = os.environ.get("EXEC_EMAIL_FROM", "nih-reporter@emory.edu")
    msg["To"] = to
    msg.set_content(re.sub(r"[*#`>]", "", summary)
                    + "\n\nFull charts are in the attached PDF.")
    msg.add_attachment(pdf, maintype="application", subtype="pdf",
                       filename="nih_weekly_executive_briefing.pdf")
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        user = os.environ.get("SMTP_USERNAME", "")
        if user:
            s.login(user, os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
    print(f"Briefing emailed to {to}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
