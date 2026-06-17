"""Summary generation: executive summaries, team digests, and single-item briefs.

Uses the Claude API when ANTHROPIC_API_KEY is set; otherwise falls back to a
template-based summary so the app always produces something useful.
"""

import json
import os
import re

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


_EMPTY_QUERY = {
    "organization": None, "all_institutions": False, "topic": None, "pi_name": None,
    "ic_codes": [], "activity_codes": [], "fiscal_years": [], "days_back": None,
    "newly_added": False, "active_only": False,
}


def _heuristic_parse(question: str, current_fy: int, ic_list, activity_list) -> dict:
    """Regex fallback that extracts the most common windows/scope from text."""
    q = (question or "").lower()
    out = dict(_EMPTY_QUERY)
    out["ic_codes"], out["activity_codes"], out["fiscal_years"] = [], [], []
    m = re.search(r"(?:last|past|previous)\s+(\d+)\s+(?:fiscal\s+years?|fys?|fy)", q)
    if m:
        n = int(m.group(1))
        out["fiscal_years"] = [current_fy - i for i in range(max(n, 1))]
    for y in re.findall(r"\bfy\s?(\d{4})\b", q) + re.findall(r"\b(20\d{2})\b", q):
        yi = int(y)
        if 2000 <= yi <= current_fy and yi not in out["fiscal_years"]:
            out["fiscal_years"].append(yi)
    for y in re.findall(r"\bfy\s?'?(\d{2})\b", q):  # 2-digit, e.g. "fy26"
        yi = 2000 + int(y)
        if 2000 <= yi <= current_fy and yi not in out["fiscal_years"]:
            out["fiscal_years"].append(yi)
    md = re.search(r"(?:last|past|previous)\s+(\d+)\s+days?", q)
    if md:
        out["days_back"] = int(md.group(1))
    for ic in ic_list:
        if re.search(r"\b" + re.escape(ic.lower()) + r"\b", q):
            out["ic_codes"].append(ic)
    for ac in activity_list:
        if re.search(r"\b" + re.escape(ac.lower()) + r"\b", q):
            out["activity_codes"].append(ac)
    if any(w in q for w in ("all institutions", "across institutions", "nationwide",
                            "every institution", "all universities", "any institution")):
        out["all_institutions"] = True
    # Comparison / trend intent: pull a range of fiscal years, not just the one
    # the user named, so "compare FY26 to previous years" has prior years to use.
    if any(w in q for w in (
            "compare", "comparison", "versus", " vs ", "year over year",
            "year-over-year", "previous year", "previous fiscal", "prior year",
            "prior fiscal", "previous years", "prior years", "over the years",
            "each year", "all years", "all previous", "historical", "history",
            "trend", "past years", "earlier years", "year by year", "yearly",
            "every year", "by year")) and len(out["fiscal_years"]) <= 1:
        out["fiscal_years"] = [current_fy - i for i in range(6)]
    if (re.search(r"\bactive\b", q) or re.search(r"\bongoing\b", q)
        or "currently funded" in q or "currently held" in q) and \
            any(w in q for w in ("grant", "award", "project", "fund", "portfolio", "pi")):
        out["active_only"] = True
    return out


def _extract_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


def parse_query(question: str, current_fy: int, ic_list, activity_list):
    """Extract NIH RePORTER search criteria from a natural-language request.

    Returns ``(criteria_dict, engine)``. The criteria drive the data pull so the
    question's window/scope (e.g. "over the last 4 fiscal years") takes priority
    over any manual filters. Falls back to a regex heuristic without a key.
    """
    heuristic = _heuristic_parse(question, current_fy, ic_list, activity_list)
    if not claude_available():
        return heuristic, "heuristic"
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        "Extract NIH RePORTER search parameters from the user's request below. "
        f"The current NIH fiscal year is FY{current_fy}. Convert relative time "
        "windows to explicit values: 'last N fiscal years' means the N most recent "
        f"fiscal years including FY{current_fy} (e.g. last 4 -> "
        f"[{current_fy}, {current_fy-1}, {current_fy-2}, {current_fy-3}]); "
        "'last N days' means days_back=N. IMPORTANT: if the user asks to COMPARE "
        "across years, see a trend/history, or says 'previous years', 'prior "
        "years', 'year over year', 'all years', 'each year', or 'all previous "
        f"years', return a RANGE of fiscal years (FY{current_fy} and the 5 prior: "
        f"[{current_fy}, {current_fy-1}, {current_fy-2}, {current_fy-3}, "
        f"{current_fy-4}, {current_fy-5}]) — never just one year. "
        f"Only use IC abbreviations from this list: {', '.join(ic_list)}. "
        f"Only use activity codes from: {', '.join(activity_list)}. "
        "Respond with ONLY a JSON object (no prose, no code fence) with keys: "
        "organization (string or null), all_institutions (boolean), topic (string "
        "or null), pi_name (string or null), ic_codes (array), activity_codes "
        "(array), fiscal_years (array of integers), days_back (integer or null), "
        "newly_added (boolean), active_only (boolean: true when the user asks for "
        "active / ongoing / currently-funded grants). Use null/empty arrays/false "
        f"when the user does not specify a field.\n\nRequest: {question}"
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=600,
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(_extract_json(text))
        out = {
            "organization": (data.get("organization") or None),
            "all_institutions": bool(data.get("all_institutions")),
            "topic": (data.get("topic") or None),
            "pi_name": (data.get("pi_name") or None),
            "ic_codes": [c for c in (data.get("ic_codes") or []) if c in ic_list],
            "activity_codes": [c for c in (data.get("activity_codes") or []) if c in activity_list],
            "fiscal_years": [int(y) for y in (data.get("fiscal_years") or [])
                             if str(y).isdigit()],
            "days_back": int(data["days_back"]) if data.get("days_back") else None,
            "newly_added": bool(data.get("newly_added")),
            "active_only": bool(data.get("active_only")),
        }
        # Keep heuristic windows if the model missed an explicit one.
        if not out["fiscal_years"] and heuristic["fiscal_years"]:
            out["fiscal_years"] = heuristic["fiscal_years"]
        if out["days_back"] is None and heuristic["days_back"]:
            out["days_back"] = heuristic["days_back"]
        return out, "claude"
    except Exception:  # noqa: BLE001 - fall back to the heuristic
        return heuristic, "heuristic"


def custom_report(question: str, facts_md: str, prior: str = "") -> tuple[str, str]:
    """Answer a natural-language report request using pre-computed dataset facts.

    ``facts_md`` contains exact, deterministically computed numbers (totals,
    per-investigator grant counts, breakdowns). The model must answer using only
    those numbers - it interprets and narrates, it does not do the arithmetic.
    Returns (answer_markdown, engine) where engine is 'claude' or 'unavailable'.
    """
    if not claude_available():
        return ("_AI custom reports need an `ANTHROPIC_API_KEY`. The exact figures "
                "for your request are in the **Key numbers** panel above._", "unavailable")
    import anthropic

    client = anthropic.Anthropic()
    context = (f"\n\nEarlier in this conversation about the SAME dataset:\n{prior}\n"
               "Answer the new question below, staying consistent with that."
               if prior else "")
    prompt = (
        "You are a research analytics assistant for a university Office of the "
        "Senior Vice President for Research. Answer the user's request using ONLY "
        "the dataset facts provided below, which were computed deterministically "
        "from NIH RePORTER data. Do not invent or recompute numbers - quote the "
        "figures given. If the facts do not contain enough to answer (e.g. the "
        "pulled window is too narrow, or a needed breakdown is missing), say so "
        "plainly and tell the user how to adjust the query (widen the look-back, "
        "select a full fiscal year, remove filters). Give a direct answer first, "
        "then a brief supporting explanation. Note that counts reflect only the "
        "awards in the current result set, not an investigator's full career. "
        "If the user asks for a chart/graph/plot, do NOT refuse — the app renders "
        "the chart separately; just provide the relevant per-category breakdown "
        "(the facts include funding and counts by fiscal year, IC, activity code, "
        "application type, state, and organization)."
        f"{context}\n\n"
        f"User request:\n{question}\n\n"
        f"Dataset facts:\n{facts_md}"
    )
    response = client.messages.create(
        model=MODEL, max_tokens=2048, thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Model declined the request")
    return next((b.text for b in response.content if b.type == "text"), ""), "claude"


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


AI_CLASSIFY_GUIDANCE = """\
You are triaging federal updates for the Senior Vice President for Research \
(SVPR) and government affairs team at Emory University - a biomedical-heavy \
research institution where the large majority of federal funding comes from \
NIH/HHS. Key strengths: medicine, public health (deep CDC ties), vaccines \
and infectious disease, cancer, neuroscience, clinical trials, and primate \
research (Emory National Primate Research Center). The portfolio agencies \
are NIH/HHS (dominant), NSF, DOE, DOD research arms (DARPA, service labs), \
NASA, FDA, and CDC. Weight their actions accordingly: an NIH funding-policy \
change (caps on grants per PI, salary cap, indirect costs, paylines), human \
subjects / Common Rule changes, clinical trial regulation, animal/primate \
research policy, biosafety or select agent rules, CDC funding actions, and \
legislative/budget actions (appropriations, continuing resolutions, \
rescission packages touching research agencies) matter far more here than \
at a typical university. Example: an NIH RFI proposing to cap the number of \
Research Project Grants per PI is CRITICAL for this institution even though \
RFIs are normally moderate. Routine agency paperwork - patent license \
notices, government-owned invention notices, meeting announcements - is \
NOT relevant even when it comes from NIH.

They care about federal \
actions that affect the research enterprise: regulations, executive actions, \
agency policy, compliance requirements, and research budget/funding POLICY.

The office's own federal-updates tracking covers, concretely: indirect cost \
rate actions and their litigation status, foreign subaward and research \
security policy, award terminations / appeals / closeout rules, executive \
orders and the agency guidance implementing them (e.g. clinical research \
inclusion policy changes), grants policy / uniform guidance, compliance \
regimes (human subjects, animal/primate, biosafety, misconduct, export \
controls), and the federal fiscal outlook for research agencies. Items in \
those lanes are relevant; items outside them are not.

First decide relevance. relevant=false for items the SVPR would not need: \
science press releases and discovery stories, podcasts/videos/episodes, \
individual grant awards ('agency invests $X in...'), prizes, event and \
seminar announcements, individual funding opportunities, notices about \
non-research programs (benefits, customs, etc.), wildlife/environmental \
permit notices (endangered species recovery permits, incidental take - \
these authorize 'scientific research' but are not research policy), \
anything from wildlife/land/food-inspection agencies (firearms or \
conservation rules, poultry/livestock inspection, fisheries, hunting), routine \
advisory committee paperwork (committee renewals, meeting notices, proposal \
review panels), Paperwork Reduction Act information-collection boilerplate, \
and topic-specific health/program RFCs that do not touch research \
administration. relevant=true for rules, proposed rules, executive orders, \
OMB/agency guidance, policy notices, compliance/disclosure requirements, \
budget actions, and RFIs on research policy or research administration.

OMB/EOP memos NOT touching research, grants, or funding (DHS operations, \
cybersecurity logging, procurement, discount rates, agency reopenings) are \
NOT relevant.

Then assign each relevant item one level:
- CRITICAL: immediate action or major disruption. ALWAYS critical: OMB or \
Executive Office actions that DO touch research/grants/funding; salary cap \
/ PI cap changes; terminations, funding freezes, rescissions, stop-work \
orders; executive orders affecting research.
- HIGH: action likely required - new compliance/disclosure requirements, \
final rules with effective dates, deadlines, indirect cost changes.
- MODERATE: worth tracking - proposed rules, comment periods, RFIs, draft \
guidance.
- INFO: relevant but routine - reports, minor administrative notices.
Judge by what the document actually DOES, not incidental words: a NIST \
notice that merely mentions 'withdrawn' submissions is not critical. \
For irrelevant items still return a level (INFO is fine)."""


def ai_classify(items: list, batch_size: int = 20) -> list:
    """Reclassify items with Claude in small batches.

    Resilient by design: each batch is independent, and if a batch fails
    (parse error, refusal, timeout) its items are KEPT and flagged
    needs_review rather than dropped - a model hiccup must never empty the
    feed. Returns all items; never raises.
    """
    import json

    import anthropic

    if not items:
        return items
    client = anthropic.Anthropic()
    schema = {
        "type": "object",
        "properties": {
            "levels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "level": {"type": "string", "enum": LEVELS},
                        "relevant": {"type": "boolean"},
                    },
                    "required": ["id", "level", "relevant"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["levels"],
        "additionalProperties": False,
    }

    result_by_id: dict = {}
    failed_ids: set = set()
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        payload = [
            {"id": it["id"], "agency": it.get("agency", ""), "source": it.get("source", ""),
             "title": it.get("title", ""), "summary": (it.get("summary") or "")[:400]}
            for it in batch
        ]
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=8000,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[{
                    "role": "user",
                    "content": f"{AI_CLASSIFY_GUIDANCE}\n\nItems:\n{json.dumps(payload)}",
                }],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("model declined")
            text = next(b.text for b in response.content if b.type == "text")
            for r in json.loads(text)["levels"]:
                result_by_id[r["id"]] = r
        except Exception:  # noqa: BLE001 - keep this batch, judge the rest
            failed_ids.update(it["id"] for it in batch)

    out = []
    for it in items:
        item = dict(it)
        res = result_by_id.get(item["id"])
        if res:
            if res["level"] in LEVELS:
                item["level"] = res["level"]
            item["relevant"] = bool(res["relevant"])
            item["ai_classified"] = True
        elif item["id"] in failed_ids:
            # Unjudged due to a batch failure: keep it, flag for review.
            item["relevant"] = True
            item["needs_review"] = True
        # Watchlist floor only - the model's judgment is otherwise final.
        if item.get("watchlist_hits") or item.get("watchlist_targeted"):
            item["relevant"] = True
            if LEVELS.index(item["level"]) > LEVELS.index("HIGH"):
                item["level"] = "HIGH"
        out.append(item)
    return out



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
