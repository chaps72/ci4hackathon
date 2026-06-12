"""Summary generation: executive summaries, team digests, and single-item briefs.

Uses the Claude API when ANTHROPIC_API_KEY is set; otherwise falls back to a
template-based summary so the app always produces something useful.
"""

import os

from .classify import LEVELS, LEVEL_EMOJI

MODEL = "claude-opus-4-8"

SUMMARY_STYLES = {
    "Executive summary": (
        "Write an executive summary for university research leadership (VP for Research, deans). "
        "Open with a 2-3 sentence bottom line. Then cover the most consequential items in order of "
        "urgency, each with what happened, who is affected, and the recommended action or owner. "
        "Close with a short 'no action needed' line listing anything informational. "
        "Keep it under 400 words. Use plain prose and short bullets, no hype."
    ),
    "Team digest": (
        "Write a digest for research administrators and grants staff. Group items by criticality "
        "level (Critical, High, Moderate, Info). For each item give one or two sentences on what it "
        "is and any deadline or required action. Practical tone, bullets are fine."
    ),
    "One-paragraph brief": (
        "Write a single tight paragraph (under 120 words) summarizing the overall picture: what's "
        "urgent, what's coming, and the single most important action for the team this week."
    ),
}


def _items_block(items: list) -> str:
    lines = []
    for it in items:
        lines.append(
            f"- [{it.get('level', 'INFO')}] {it.get('date', '')} | {it.get('agency', '')} | "
            f"{it.get('title', '')}\n  Summary: {it.get('summary', '')}\n  Source: {it.get('url', '')}"
        )
    return "\n".join(lines)


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def generate_summary(items: list, style: str = "Executive summary",
                     extra_instructions: str = "") -> tuple[str, str]:
    """Return (summary_markdown, engine) where engine is 'claude' or 'template'."""
    if not items:
        return "_No items selected._", "template"
    if claude_available():
        try:
            return _claude_summary(items, style, extra_instructions), "claude"
        except Exception:  # noqa: BLE001 - fall back rather than break the dashboard
            pass
    return _template_summary(items, style), "template"


def _claude_summary(items: list, style: str, extra_instructions: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    instructions = SUMMARY_STYLES.get(style, SUMMARY_STYLES["Executive summary"])
    if extra_instructions:
        instructions += f"\n\nAdditional instructions from the user: {extra_instructions}"

    prompt = (
        "You are preparing an internal awareness summary of recent federal research policy and "
        "funding updates for a university research team. Use only the items provided; do not "
        "invent details, dates, or requirements. Criticality levels were assigned by a keyword "
        "screen and may be imperfect - use judgment when ordering items.\n\n"
        f"{instructions}\n\n"
        f"Items ({len(items)}):\n{_items_block(items)}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Model declined the request")
    return next((b.text for b in response.content if b.type == "text"), "")


def _template_summary(items: list, style: str) -> str:
    by_level = {lvl: [] for lvl in LEVELS}
    for it in items:
        by_level.setdefault(it.get("level", "INFO"), []).append(it)

    n_crit, n_high = len(by_level["CRITICAL"]), len(by_level["HIGH"])
    headline = (
        f"**Bottom line:** {len(items)} federal research updates in this period - "
        f"{n_crit} critical and {n_high} high-priority item(s) "
        f"{'require attention.' if (n_crit + n_high) else 'were found; nothing urgent.'}"
    )

    if style == "One-paragraph brief":
        top = by_level["CRITICAL"] + by_level["HIGH"]
        names = "; ".join(it["title"] for it in top[:3]) or "no urgent items"
        return (
            f"{headline} Most important: {names}. "
            f"Plus {len(by_level['MODERATE'])} item(s) to track and "
            f"{len(by_level['INFO'])} informational notice(s)."
        )

    parts = [headline, ""]
    for lvl in LEVELS:
        if not by_level[lvl]:
            continue
        parts.append(f"### {LEVEL_EMOJI[lvl]} {lvl.title()} ({len(by_level[lvl])})")
        for it in by_level[lvl]:
            parts.append(f"- **{it['title']}** ({it.get('agency', '')}, {it.get('date', '')})")
            if it.get("summary"):
                parts.append(f"  - {it['summary'][:300]}")
        parts.append("")
    parts.append(
        "_Generated with the built-in template engine. Set ANTHROPIC_API_KEY for "
        "AI-written summaries._"
    )
    return "\n".join(parts)
