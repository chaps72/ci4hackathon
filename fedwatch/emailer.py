"""Email-safe digest builder.

Produces a plain-text version plus an HTML version designed to be safe to send:
- every dynamic value is HTML-escaped (no injection from feed content)
- inline styles only, no scripts, no external images or tracking pixels
- links restricted to http(s) URLs from the source feeds
- a ready-to-send multipart .eml file for download
"""

import html
from datetime import datetime
from email.message import EmailMessage

from .classify import LEVELS, LEVEL_EMOJI

# Emory brand palette
EMORY_BLUE = "#012169"
EMORY_GOLD = "#f2a900"
EMORY_LIGHT_BLUE = "#007dba"
EMORY_GRAY = "#6d6e71"

LEVEL_COLORS = {
    "CRITICAL": "#c0392b",       # keep red/orange semantics for urgency
    "HIGH": "#d35400",
    "MODERATE": EMORY_GOLD,
    "INFO": EMORY_LIGHT_BLUE,
}


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def _deadline_badges(it: dict, e) -> str:
    """Small colored pills for an action deadline and/or comment opportunity,
    drawn from the Federal Register structured fields. '' when neither applies."""
    pills = []
    if it.get("comment_due"):
        pills.append(('#c0392b', f'⏰ Comment due {e(it["comment_due"])}'))
    elif it.get("effective_on"):
        pills.append((EMORY_LIGHT_BLUE, f'⏰ Effective {e(it["effective_on"])}'))
    if it.get("comment_opportunity"):
        link = _safe_url(it.get("comment_url", "")) or _safe_url(it.get("url", ""))
        label = "💬 Comment opportunity"
        text = f'<a href="{e(link)}" style="color:#ffffff;text-decoration:none;">{label}</a>' if link else label
        pills.append((EMORY_GOLD, text))
    if not pills:
        return ""
    spans = "".join(
        f'<span style="display:inline-block;background:{c};color:#ffffff;'
        f'font-size:11px;font-weight:bold;padding:2px 8px;border-radius:10px;'
        f'margin:4px 6px 0 0;">{t}</span>' for c, t in pills)
    return f'<div style="padding-top:4px;">{spans}</div>'


def build_plain_text(items: list, summary_md: str = "", title: str = "Federal Research Update") -> str:
    lines = [title, "=" * len(title),
             f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    if summary_md:
        lines += ["SUMMARY", "-------", summary_md, ""]
    lines += ["ITEMS", "-----"]
    for lvl in LEVELS:
        group = [i for i in items if i.get("level") == lvl]
        if not group:
            continue
        lines.append(f"\n[{lvl}]")
        for it in group:
            lines.append(f"* {it.get('title', '')}")
            lines.append(f"  {it.get('agency', '')} | {it.get('date', '')} | {it.get('source', '')}")
            if it.get("summary"):
                lines.append(f"  {it['summary'][:400]}")
            if _safe_url(it.get("url", "")):
                lines.append(f"  Link: {it['url']}")
    lines += ["", "--", "Sent by FedWatch (internal). Reply to the research operations team with questions."]
    return "\n".join(lines)


def build_html(items: list, summary_md: str = "", title: str = "Federal Research Update") -> str:
    e = html.escape
    rows = []
    for lvl in LEVELS:
        group = [i for i in items if i.get("level") == lvl]
        if not group:
            continue
        color = LEVEL_COLORS[lvl]
        rows.append(
            f'<tr><td style="padding:14px 0 6px 0;font:bold 14px Arial,sans-serif;'
            f'color:{color};">{LEVEL_EMOJI[lvl]} {e(lvl.title())} ({len(group)})</td></tr>'
        )
        for it in group:
            url = _safe_url(it.get("url", ""))
            title_html = e(it.get("title", ""))
            if url:
                title_html = f'<a href="{e(url)}" style="color:{EMORY_BLUE};">{title_html}</a>'
            rows.append(
                '<tr><td style="padding:6px 0 10px 12px;border-left:3px solid '
                f'{color};font:13px Arial,sans-serif;color:#2c3e50;">'
                f'<div style="font-weight:bold;">{title_html}</div>'
                + (f'<div style="display:inline-block;background:{EMORY_GRAY};color:#fff;'
                   f'font-size:11px;font-weight:bold;padding:2px 8px;border-radius:10px;'
                   f'margin:3px 0;">🔄 {e(it.get("update_note",""))}</div>' if it.get("update_note") else "")
                + f'<div style="color:#7f8c8d;font-size:12px;">{e(it.get("agency", ""))} &middot; '
                f'{e(it.get("date", ""))} &middot; {e(it.get("source", ""))}</div>'
                + _deadline_badges(it, e)
                + f'<div style="padding-top:3px;">{e((it.get("summary") or "")[:400])}</div>'
                + (f'<div style="padding-top:6px;background:#eef1f7;border-radius:4px;'
                   f'padding:8px 10px;margin-top:6px;font-size:12px;">'
                   f'<b style="color:{EMORY_BLUE};">Emory impact</b>'
                   + (f' &middot; <b>{e(it.get("exposure","").upper())} severity</b>' if it.get("exposure") else "")
                   + f'<br>{e(it.get("impact",""))}'
                   + (f'<br><b>SVPR office:</b> {e(it.get("svpr_impact",""))}' if it.get("svpr_impact") else "")
                   + (f'<br><b>Owner:</b> {e(it.get("owner",""))}' if it.get("owner") else "")
                   + (f' &middot; <b>Action:</b> {e(it.get("action",""))}' if it.get("action") else "")
                   + '</div>' if it.get("impact") else "")
                + (f'<div style="padding:8px 10px;margin-top:6px;font-size:12px;'
                   f'background:#fff7e6;border-left:3px solid {EMORY_GOLD};border-radius:4px;">'
                   f'<b style="color:{EMORY_GRAY};">📰 In the news</b><br>{e(it.get("news",""))}'
                   + ("".join(f'<br><a href="{e(u)}" style="color:{EMORY_LIGHT_BLUE};">{e(u[:70])}</a>'
                              for u in (it.get("news_sources") or []) if _safe_url(u)))
                   + '</div>' if it.get("news") else "")
                + "</td></tr>"
            )

    summary_html = ""
    if summary_md:
        summary_html = (
            '<tr><td style="padding:12px;background:#f4f6f7;border-radius:6px;'
            'font:13px Arial,sans-serif;color:#2c3e50;white-space:pre-wrap;">'
            f"{e(summary_md)}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:20px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0">
<tr><td style="background:{EMORY_BLUE};padding:16px 18px;border-bottom:4px solid {EMORY_GOLD};">
<div style="font:bold 20px Georgia,'Times New Roman',serif;color:#ffffff;">{e(title)}</div>
<div style="font:12px Arial,sans-serif;color:#d6deef;padding-top:4px;">
Generated {e(datetime.now().strftime('%Y-%m-%d %H:%M'))} &middot; Internal use</div>
</td></tr>
<tr><td style="height:14px;"></td></tr>
{summary_html}
{''.join(rows)}
<tr><td style="padding-top:18px;border-top:2px solid {EMORY_GOLD};margin-top:12px;
font:11px Arial,sans-serif;color:{EMORY_GRAY};">
Sent by FedWatch (internal awareness tool). No tracking pixels, no external images.
Reply to the research operations team with questions.</td></tr>
</table></td></tr></table>
</body></html>"""



def build_archive_index(dates: list, title: str = "FedWatch — NIH & Research Policy Digests") -> str:
    """A browsable index page linking every published daily digest (newest first)."""
    esc = html.escape
    rows = []
    for d in sorted(dates, reverse=True):
        rows.append(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid #e3e7ee;'
            f'font:14px Arial,sans-serif;">'
            f'<a href="digests/{esc(d)}.html" style="color:{EMORY_BLUE};text-decoration:none;">'
            f'📄 {esc(d)}</a></td></tr>')
    latest = f'digests/{esc(sorted(dates, reverse=True)[0])}.html' if dates else "#"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title></head>
<body style="margin:0;padding:0;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0">
<tr><td style="background:{EMORY_BLUE};padding:18px 20px;border-bottom:4px solid {EMORY_GOLD};">
<div style="font:bold 22px Georgia,'Times New Roman',serif;color:#ffffff;">FedWatch</div>
<div style="font:13px Arial,sans-serif;color:#d6deef;padding-top:4px;">
NIH &amp; Research Policy Digests · Office of the SVPR</div></td></tr>
<tr><td style="height:16px;"></td></tr>
<tr><td style="font:14px Arial,sans-serif;color:#2c3e50;padding-bottom:12px;">
Daily digests of federal research-policy updates affecting Emory, curated and analyzed with Claude.
Published each weekday at 5pm ET. <a href="{latest}" style="color:{EMORY_LIGHT_BLUE};font-weight:bold;">
Open the latest &rarr;</a></td></tr>
<tr><td style="font:bold 13px Arial,sans-serif;color:{EMORY_GRAY};text-transform:uppercase;
letter-spacing:.06em;padding:6px 0;">Archive</td></tr>
<tr><td><table width="100%" cellpadding="0" cellspacing="0">{''.join(rows) or '<tr><td style="font:14px Arial,sans-serif;color:#7f8c8d;padding:8px 0;">No digests published yet.</td></tr>'}</table></td></tr>
<tr><td style="padding-top:20px;border-top:2px solid {EMORY_GOLD};margin-top:12px;
font:11px Arial,sans-serif;color:{EMORY_GRAY};">Internal awareness tool. Reply to the research operations team with questions.</td></tr>
</table></td></tr></table></body></html>"""

def build_eml(items: list, summary_md: str = "", title: str = "Federal Research Update",
              sender: str = "fedwatch@your-institution.edu",
              recipients: str = "research-team@your-institution.edu") -> bytes:
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender
    msg["To"] = recipients
    msg.set_content(build_plain_text(items, summary_md, title))
    msg.add_alternative(build_html(items, summary_md, title), subtype="html")
    return bytes(msg)
