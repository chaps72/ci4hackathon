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
    "newly_added": False, "active_only": False, "date_from": None, "date_to": None,
    "group_by": None, "chart_dim": None, "chart_metric": None,
}

# Chart hints the model may attach to a parse: the one breakdown that best
# illustrates the question, and whether it is about dollars or counts.
_CHART_DIMS = ("fy", "ic", "activity", "app_type", "org", "state", "week", "month")

_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
           "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
           "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTH_LAST = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30,
               10: 31, 11: 30, 12: 31}


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
    # Weekly / monthly grouping (including conversational phrasings) — detected
    # FIRST so a weekly/monthly comparison doesn't get treated as a year comparison.
    if any(w in q for w in ("weekly", "per week", "by week", "each week",
                            "week by week", "week-by-week", "week over week",
                            "this week", "last week", "past week", "previous week",
                            "recent week", "few weeks", "couple weeks", "couple of weeks",
                            "last several weeks", "weeks ago", "per-week")):
        out["group_by"] = "week"
    elif any(w in q for w in ("monthly", "per month", "by month", "each month",
                              "month by month", "month over month", "this month",
                              "last month", "recent month", "few months")):
        out["group_by"] = "month"
    # Recent weekly/monthly activity without explicit dates -> bound the pull so
    # week/month buckets (and a week-over-week comparison) are actually possible.
    if (out["group_by"] and not out["fiscal_years"] and not out["date_from"]
            and not out["days_back"]):
        out["days_back"] = 70 if out["group_by"] == "week" else 210
    # Year comparison/trend -> a RANGE of fiscal years. Skipped when the question
    # is a weekly/monthly comparison (group_by set above).
    if not out["group_by"] and any(w in q for w in (
            "compare", "comparison", "versus", " vs ", "year over year",
            "year-over-year", "previous year", "previous fiscal", "prior year",
            "prior fiscal", "previous years", "prior years", "over the years",
            "each year", "all years", "all previous", "historical", "history",
            "trend", "past years", "earlier years", "year by year", "yearly",
            "every year", "by year")) and len(out["fiscal_years"]) <= 1:
        out["fiscal_years"] = [current_fy - i for i in range(6)]
    # 'Entire history' / 'as far back as possible' -> last 10 FYs (data goes back
    # to FY1985, but pulls are capped for performance).
    if not out["group_by"] and any(w in q for w in (
            "entire history", "all available years", "as far back", "since 1985",
            "full history", "all-time", "all time", "every year since", "as early as")):
        out["fiscal_years"] = [current_fy - i for i in range(10)]
    if (re.search(r"\bactive\b", q) or re.search(r"\bongoing\b", q)
        or "currently funded" in q or "currently held" in q) and \
            any(w in q for w in ("grant", "award", "project", "fund", "portfolio", "pi")):
        out["active_only"] = True
    # Named months -> an award-notice date range in the current FY year.
    months = sorted({n for name, n in _MONTHS.items()
                     if re.search(r"\b" + name + r"\b", q)})
    if months and not out["fiscal_years"]:
        y = current_fy
        lo, hi = months[0], months[-1]
        out["date_from"] = f"{y}-{lo:02d}-01"
        out["date_to"] = f"{y}-{hi:02d}-{_MONTH_LAST[hi]:02d}"
    return out


def _valid_date(s):
    return s if isinstance(s, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def _extract_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


def _validated(data: dict, question: str, ic_list, activity_list) -> dict:
    """Coerce a model-produced criteria dict into a safe, complete one."""
    return {
        "organization": (data.get("organization") or None),
        "all_institutions": bool(data.get("all_institutions")),
        "topic": (data.get("topic") or None),
        "pi_name": (data.get("pi_name") or None),
        "ic_codes": [c for c in (data.get("ic_codes") or []) if c in ic_list],
        "activity_codes": [c for c in (data.get("activity_codes") or [])
                           if c in activity_list],
        "fiscal_years": [int(y) for y in (data.get("fiscal_years") or [])
                         if str(y).isdigit()],
        "days_back": int(data["days_back"]) if data.get("days_back") else None,
        # Only honor 'newly added' when the user literally said it — guards
        # against 'new awards' being read as the database-added flag.
        "newly_added": bool(data.get("newly_added"))
        and bool(re.search(r"newly added|recently added", question or "", re.I)),
        "active_only": bool(data.get("active_only")),
        "date_from": _valid_date(data.get("date_from")),
        "date_to": _valid_date(data.get("date_to")),
        "group_by": data.get("group_by") if data.get("group_by") in ("week", "month") else None,
        "chart_dim": data.get("chart_dim") if data.get("chart_dim") in _CHART_DIMS else None,
        "chart_metric": data.get("chart_metric")
        if data.get("chart_metric") in ("funding", "count") else None,
    }


# Shared field list for prompts that must emit a criteria JSON object.
_CRITERIA_FIELDS = (
    "organization (string or null), all_institutions (boolean), topic (string "
    "or null), pi_name (string or null), ic_codes (array), activity_codes "
    "(array), fiscal_years (array of integers), days_back (integer or null), "
    "newly_added (boolean), active_only (boolean), date_from (YYYY-MM-DD or "
    "null), date_to (YYYY-MM-DD or null), group_by ('week', 'month', or null), "
    "chart_dim (one of 'fy','ic','activity','app_type','org','state','week',"
    "'month', or null), chart_metric ('funding', 'count', or null)")

_CHART_HINT_RULES = (
    "Also decide how the answer is best SHOWN: set chart_dim to the ONE "
    "breakdown that best illustrates this question — 'fy' for year trends/"
    "comparisons, 'week'/'month' for recent activity over time, 'ic' for "
    "institute mix, 'activity' for mechanism mix, 'app_type' for new-vs-renewal, "
    "'org' for cross-institution comparisons, 'state' for geography — and "
    "chart_metric to 'funding' when the question is about dollars, 'count' when "
    "it is about how many. Leave them null only when no chart fits (e.g. a "
    "single named award's details).")


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
        "You translate a research-office question into an NIH RePORTER data pull. "
        "FIRST, reason about what the person is actually trying to learn — the "
        "real-world question behind the words — then choose the parameters that "
        "would best ANSWER it. Do not keyword-match. Think it through: What entity "
        "is in focus (an institution, a PI, a topic, the whole NIH)? What time "
        "frame would actually answer this (a single year, a multi-year trend, a "
        "recent window, specific months)? What grain (week, month, year, or none)? "
        "Pick the pull that a knowledgeable analyst would run to answer the "
        "question — not the most literal reading of any one word. For example "
        "'how is our funding trending' implies several years even though no number "
        "is given; 'what came in this week vs the last few weeks' implies a recent "
        "window grouped by week, NOT a 7-day cutoff; 'compare A to B' only means "
        "multiple fiscal years if A and B are years. When the question is "
        "self-evidently about home turf, the institution is Emory. Use the field "
        "rules below to encode that reasoned intent.\n\n"
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
        "NIH RePORTER project data goes back to FY1985; if the user asks for the "
        "'entire history', 'all available years', 'as far back as possible', or "
        f"'since 1985', return the last 10 fiscal years ({current_fy} down to "
        f"{current_fy-9}) — pulls are capped for performance. "
        "If the user names specific months or a calendar date range (e.g. 'April, "
        "May and June', 'since March', 'between Jan 1 and Mar 31'), set date_from "
        f"and date_to as YYYY-MM-DD, assuming year {current_fy} unless a year is "
        "given (date_from = first day of the earliest month, date_to = last day of "
        "the latest month). If the user wants a weekly or monthly breakdown — "
        "including conversational phrasings like 'this week', 'last week', 'the "
        "previous few weeks', 'week over week', 'on a weekly basis', 'per week', "
        "'by month', 'this month' — set group_by to 'week' or 'month'. Do NOT treat "
        "'weekly'/'this week' as days_back=7. For RECENT weekly activity with no "
        "explicit dates (e.g. 'this week vs the previous few weeks'), ALSO set "
        "days_back to about 70 (≈10 weeks) so weekly buckets and a week-over-week "
        "comparison are possible; for recent monthly activity set days_back ≈ 210. "
        f"Only use IC abbreviations from this list: {', '.join(ic_list)}. "
        f"Only use activity codes from: {', '.join(activity_list)}. "
        "IMPORTANT: 'newly_added' means projects RECENTLY ADDED TO THE RePORTER "
        "DATABASE — it is NOT for new awards. Do NOT set it for 'new awards', "
        "'new grants', 'new NIH funding', or Type-1/new application type; only "
        "set it if the user literally says 'newly added to RePORTER' or 'recently "
        "added to the database'. A phrase like 'new awards per week' just means "
        "awards issued in the date window — leave newly_added false. "
        f"{_CHART_HINT_RULES} "
        "Respond with ONLY a JSON object (no prose, no code fence) with keys: "
        f"{_CRITERIA_FIELDS}. "
        "Use null/empty arrays/false when the user does not specify a field."
        f"\n\nRequest: {question}"
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1600, thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(_extract_json(text))
        out = _validated(data, question, ic_list, activity_list)
        # Keep heuristic windows if the model missed an explicit one.
        if not out["fiscal_years"] and heuristic["fiscal_years"]:
            out["fiscal_years"] = heuristic["fiscal_years"]
        if out["days_back"] is None and heuristic["days_back"]:
            out["days_back"] = heuristic["days_back"]
        if not out["date_from"] and heuristic["date_from"]:
            out["date_from"], out["date_to"] = heuristic["date_from"], heuristic["date_to"]
        if not out["group_by"] and heuristic["group_by"]:
            out["group_by"] = heuristic["group_by"]
        return out, "claude"
    except Exception:  # noqa: BLE001 - fall back to the heuristic
        return heuristic, "heuristic"


def plan_followup(followup: str, scope: dict, current_fy: int, ic_list,
                  activity_list, n_items: int = 0, history: str = ""):
    """Reason about how a follow-up changes the data scope — the follow-up
    analog of ``parse_query``, anchored on the CURRENT scope so constraints can
    be added, changed, or REMOVED (not just merged on top). ``history`` is the
    conversation so far, used to resolve references ('that year', 'those
    grants') and to read the follow-up in context.

    Returns ``{"action": "reuse"|"refetch", "scope": <full criteria dict>}``,
    or ``None`` when Claude is unavailable or errors — the caller then falls
    back to the keyword heuristics.
    """
    if not claude_available():
        return None
    import anthropic

    client = anthropic.Anthropic()
    cur = {k: scope.get(k, v) for k, v in _EMPTY_QUERY.items()}
    hist_block = (f"Conversation so far (use it to work out how the follow-up "
                  f"relates — a refinement, a pivot, or a reference like 'those "
                  f"grants' or 'that year' that resolves to something earlier):\n"
                  f"{history}\n\n" if history else "")
    prompt = (
        "You manage the data scope of an ongoing NIH RePORTER analysis "
        "conversation. The data currently on screen was pulled with the scope "
        "below; the user has asked a follow-up. FIRST read the follow-up in the "
        "context of the conversation and reason about what it actually needs, "
        "then decide:\n"
        "- action 'reuse': it can be answered from the records already pulled "
        "(a different cut, ranking, or summary of the SAME data). Keep the "
        "scope's constraints exactly as they are (you may still update "
        "chart_dim/chart_metric to fit the follow-up).\n"
        "- action 'refetch': it needs data outside the current pull. Then "
        "output the COMPLETE new scope: start from the current one and ADD, "
        "CHANGE, or REMOVE constraints as the follow-up implies. Removing means "
        "emptying the field — 'all institutes, not just NCI' -> ic_codes: []; "
        "'not just R01s' -> activity_codes: []; 'drop the topic filter' -> "
        "topic: null; 'all institutions' -> all_institutions: true and "
        "organization: null; 'not just active grants' -> active_only: false; "
        "'beyond this year' -> a wider fiscal_years list.\n"
        "Constraints the follow-up doesn't mention stay as they are — they are "
        "the conversation's context. EXCEPTION: if the follow-up clearly starts "
        "a new direction ('instead', 'new search', a different institution/"
        "topic/PI as the subject), rebuild the scope from just the new request "
        "(home institution Emory when none is named).\n"
        f"The current NIH fiscal year is FY{current_fy}. Time rules: 'last N "
        "fiscal years' = the N most recent including the current; comparing "
        "years / trends = a RANGE of years (current and 5 prior if unstated); "
        "weekly phrasings ('this week', 'previous few weeks') = group_by 'week' "
        "with days_back about 70, monthly = group_by 'month' with days_back "
        f"about 210. Only use IC codes from: {', '.join(ic_list)}. Only use "
        f"activity codes from: {', '.join(activity_list)}. "
        f"{_CHART_HINT_RULES}\n"
        "Respond with ONLY a JSON object (no prose): {\"action\": \"reuse\" or "
        "\"refetch\", \"scope\": {" + _CRITERIA_FIELDS + "}}.\n\n"
        f"{hist_block}"
        f"Current scope (JSON): {json.dumps(cur)}\n"
        f"Records currently pulled: {n_items}\n\n"
        f"Follow-up: {followup}"
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=1600, thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(_extract_json(text))
        action = ("refetch" if str(data.get("action", "")).lower() == "refetch"
                  else "reuse")
        new_scope = _validated(data.get("scope") or cur, followup,
                               ic_list, activity_list)
        if action == "reuse":
            # Reuse means the SAME data — only the chart hints may move.
            kept = dict(cur)
            kept["chart_dim"] = new_scope.get("chart_dim") or cur.get("chart_dim")
            kept["chart_metric"] = (new_scope.get("chart_metric")
                                    or cur.get("chart_metric"))
            new_scope = kept
        return {"action": action, "scope": new_scope}
    except Exception:  # noqa: BLE001 - caller falls back to heuristics
        return None


# Below this confidence (0-100) in its best reading of a request, the triage
# asks ONE clarifying question before running; at or above it, it just runs.
CLARIFY_CONFIDENCE = 75

_NO_CLARIFY = {"confidence": 100, "reading": "", "question": ""}


def clarify(question: str) -> dict:
    """Reason through a request BEFORE running it and self-rate confidence.

    The model works out what the person is actually trying to learn, sketches
    the report it would build (scope, window, breakdown), and rates 0-100 how
    confident it is that this reading matches the person's intent. Returns
    ``{"confidence": int, "reading": str, "question": str}`` — ``question`` is
    non-empty ONLY when confidence is below ``CLARIFY_CONFIDENCE``, so callers
    can simply run whenever it is empty.
    """
    if not claude_available():
        return dict(_NO_CLARIFY)
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        "You triage NIH RePORTER analytics requests for a university research "
        "office before they run. Work through the request step by step:\n"
        "1. What is the person actually trying to LEARN or decide — the intent "
        "behind the words?\n"
        "2. What report would a knowledgeable analyst build to answer it: which "
        "institution(s), what time window, what breakdown or comparison, dollars "
        "or counts?\n"
        "3. Are there OTHER materially different readings a reasonable person "
        "could mean? A reading is materially different only if it changes the "
        "data pulled or the shape of the answer — not the wording.\n"
        "Then rate your CONFIDENCE 0-100 that your single best reading matches "
        "their intent. Calibrate honestly: 90+ = any analyst would read it the "
        "same way; 75-89 = minor ambiguity but the sensible default reading is "
        "clearly best; below 75 = a genuinely different report could be what "
        "they want (ambiguous entity, ambiguous window for a trend, unclear "
        "metric, unclear comparison target).\n"
        "Standing defaults that do NOT lower confidence: home institution is "
        "Emory when none is named; no stated window means all available data; "
        "funding questions default to dollars. Most requests are clear enough "
        f"to run. Only if confidence is below {CLARIFY_CONFIDENCE} write ONE "
        "short question (max 25 words) that would resolve the biggest "
        "ambiguity; otherwise the question MUST be an empty string.\n"
        "Respond with ONLY a JSON object: {\"reading\": <one sentence — the "
        "report you would build>, \"confidence\": <integer 0-100>, "
        "\"question\": <string, empty unless confidence is below "
        f"{CLARIFY_CONFIDENCE}>}}.\n\n"
        f"Request: {question}"
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=800, thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(_extract_json(text))
        conf = max(0, min(100, int(data.get("confidence", 100))))
        q = (data.get("question") or "").strip()
        # Enforce the contract both ways: confident -> no question; unsure
        # without a question -> run anyway rather than block on nothing.
        if conf >= CLARIFY_CONFIDENCE or "?" not in q:
            q = ""
        return {"confidence": conf, "reading": (data.get("reading") or "").strip(),
                "question": q}
    except Exception:  # noqa: BLE001 - never block a report on triage failure
        return dict(_NO_CLARIFY)


# Fallback suggestions when no API key — one trend, one comparison, one
# concentration angle, one strategic angle.
_FALLBACK_SUGGESTIONS = [
    ("Trend over years", "Show the trend over the last 5 fiscal years as a chart, "
     "and note whether it is growing or shrinking."),
    ("Peer benchmark", "Benchmark this against peer institutions (Duke, "
     "Vanderbilt, Johns Hopkins) with a comparison chart."),
    ("Concentration risk", "How concentrated is this funding among the top PIs "
     "and the largest institute? Quote the shares and what they imply."),
    ("Renewal pipeline", "Which of these projects end within the next 12 months, "
     "and how many dollars are at stake?"),
]


def suggest_followups(question: str, facts_md: str) -> list:
    """Propose 4 useful NEXT analyses for this result set — four DIFFERENT kinds
    of analytical move, each chart-friendly and grounded in what the data shows.
    Returns a list of (button_label, follow_up_prompt) tuples."""
    if not claude_available():
        return _FALLBACK_SUGGESTIONS[:4]
    import anthropic

    client = anthropic.Anthropic()
    prompt = (
        "You advise a university research office on what to look at next in an "
        "NIH RePORTER result set. Read the user's question and the dataset facts, "
        "notice what is actually interesting in THIS data (a spike, a dominant "
        "institute, a concentration, an expiring cluster), and propose 4 follow-up "
        "analyses — one of EACH kind, so they are genuinely different moves:\n"
        "1. TREND: a change-over-time view (fiscal years, or weeks/months for "
        "recent windows).\n"
        "2. MIX: a breakdown along a dimension the user has NOT already asked "
        "about (institute, mechanism, application type, PI).\n"
        "3. COMPARISON: peers, prior years, or share-of-total context.\n"
        "4. STRATEGIC ANGLE they likely haven't considered: e.g. concentration/"
        "dependency risk, the renewal pipeline (projects ending within 12 months), "
        "rising investigators, new-money vs continuation, or the research themes "
        "in the abstracts.\n"
        "Anchor each in a specific fact when possible ('NCI is 40% of the total — "
        "how dependent are we?'), never repeat the user's original cut, and phrase "
        "each prompt so it produces a chart. Respond with ONLY a JSON array of 4 "
        "objects {\"label\": <button text, max 4 words>, \"prompt\": <full "
        "instruction to run, one sentence>}, in the order above. No prose.\n\n"
        f"Question: {question}\n\nDataset facts:\n{facts_md[:2500]}"
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=500,
            messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(_extract_json_array(text))
        out = [(str(o["label"])[:40], str(o["prompt"]))
               for o in data if o.get("label") and o.get("prompt")]
        return out[:4] or _FALLBACK_SUGGESTIONS[:4]
    except Exception:  # noqa: BLE001
        return _FALLBACK_SUGGESTIONS[:4]


def _extract_json_array(text: str) -> str:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    return text[start:end + 1] if start != -1 and end != -1 else text


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
    context = (f"\n\nEarlier in this conversation:\n{prior}\n"
               "Before answering, work out how the new question RELATES to the "
               "conversation above: a refinement of the same result set, a pivot "
               "to something new, a comparison against an earlier answer, or a "
               "reference ('those grants', 'that year', 'the largest one') that "
               "resolves to something said earlier. Answer in that light — "
               "resolve references explicitly, and when the question invites "
               "comparison, carry the relevant earlier numbers forward and state "
               "the change. The dataset facts already reflect any data that "
               "needed to be pulled for this follow-up, so answer from them "
               "directly — do NOT say the data wasn't in the original pull."
               if prior else "")
    prompt = (
        "You are a research analytics assistant for a university Office of the "
        "Senior Vice President for Research. Before writing, reason about what the "
        "person actually wants to KNOW — the decision or insight behind the "
        "question — and answer THAT, not a literal restatement of the words. Use "
        "judgment about what's worth surfacing in this specific dataset (the "
        "outliers, the trend, the concentration, the surprise), rather than "
        "mechanically reciting every field. "
        "Answer the user's request using ONLY "
        "the dataset facts provided below, which were computed deterministically "
        "from NIH RePORTER data. Do not invent or recompute numbers - quote the "
        "figures given. If the facts do not contain enough to answer (e.g. the "
        "pulled window is too narrow, or a needed breakdown is missing), say so "
        "plainly and tell the user how to adjust the query (widen the look-back, "
        "select a full fiscal year, remove filters). Give a direct answer first, "
        "then a brief supporting explanation. Note that counts reflect only the "
        "awards in the current result set, not an investigator's full career. "
        "PRIORITIZE GRAPHS over long lists/tables. Keep the narrative to a SHORT "
        "intro — 2 to 4 sentences with the headline numbers (totals, the standout "
        "items) — because one or more graphs are shown right below your answer "
        "(an interactive one the user can flip between breakdowns — institute, "
        "fiscal year, mechanism, etc. — plus extra complementary charts when more "
        "than one cut of the data is illuminating). Refer to 'the charts below' "
        "rather than describing every number. Do NOT reproduce a long table or a "
        "long bulleted list of "
        "every category; mention the top few and say the rest is in the graph. "
        "Never refuse a chart request. "
        "ALWAYS begin your answer by stating the fiscal year(s) or date window the "
        "data covers (e.g. 'FY2026:' or 'April–May 2026:'), so the reader knows the "
        "period. NIH RePORTER project data only goes back to FY1985. "
        "FORMATTING: do NOT use markdown headings (#, ##, ###); use short **bold** "
        "lead-ins and bullets, keep it clean. The request has already been "
        "clarified if needed, so just answer it. "
        "End with ONE line — '**Worth exploring next:** …' — proposing a single "
        "specific further analysis THIS data supports and the user did not ask "
        "for, picked from what stands out in the facts (a concentration worth "
        "probing, projects ending soon, a trend worth extending, a peer "
        "comparison). One sentence, no list."
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
seminar announcements, funding opportunities from agencies outside the \
portfolio, notices about \
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
budget actions, RFIs on research policy or research administration, and \
NEW NIH funding opportunities (NOFOs, RFAs, PAs, NOSIs) - the team wants \
to see new NIH grant mechanisms and RFIs (usually MODERATE; major new \
programs HIGH).

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




EMORY_PROFILE = """\
Emory University research profile (for impact analysis - reason only from \
this, do not invent specific grant numbers, PI names, dollar amounts, or \
counts you were not given):
- Among the top NIH-funded universities; the large majority of federal \
research funding is NIH/HHS. NSF, DOD, DOE, and CDC are secondary.
- Signature strengths: medicine (Emory School of Medicine), public health \
(Rollins School of Public Health, deep CDC partnership), infectious \
disease and vaccines (Emory Vaccine Center; Hope Clinic), cancer (Winship \
Cancer Institute, an NCI-designated comprehensive cancer center), \
neuroscience, cardiology, transplant, pediatrics (with Children's \
Healthcare of Atlanta), and nonhuman-primate research (Emory National \
Primate Research Center, formerly Yerkes).
- Large clinical-trials enterprise; significant human-subjects and \
animal-research (IACUC/OLAW) footprint; substantial F&A/indirect-cost \
recovery on NIH awards.
- Key offices: Office of Sponsored Programs (OSP), Office of Research \
Administration (ORA), Research Compliance & Regulatory Affairs (RCRA), \
Office of General Counsel (OGC), IACUC, IRB, Office of Government & \
Community Affairs."""

_IMPACT_GUIDANCE = """\
For each federal item, assess the concrete impact on EMORY specifically. \
Reason from Emory's research profile (given below). Be specific about WHICH \
Emory units, portfolios, or activities are affected and HOW - but never \
fabricate grant numbers, PI names, dollar figures, or counts. If the impact \
is genuinely uncertain or minimal, say so plainly.

Return, per item: an `impact` (2-3 sentences: which Emory research areas/\
offices are affected and the concrete effect), a `svpr_impact` (one \
sentence on what this specifically means for the Office of the Senior Vice \
President for Research - the central research leadership/administration: \
e.g. an institutional response to coordinate, a portfolio-level financial \
or compliance risk to own, or a policy position to take), an `exposure` \
level (high/medium/low - how much of Emory's enterprise this touches), an \
`owner` (the Emory office that should act, from the profile), and a short \
`action` (the single most useful next step, or 'Monitor' if none)."""


def analyze_emory_impact(items: list, batch_size: int = 12) -> list:
    """Add Emory-specific impact analysis to each item (agent behavior).

    Grounded in EMORY_PROFILE; resilient (per-batch, never raises). Sets
    impact/exposure/owner/action on each item. No-op without an API key.
    """
    import json

    import anthropic

    if not items or not claude_available():
        return items
    client = anthropic.Anthropic()
    schema = {
        "type": "object",
        "properties": {"impacts": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "impact": {"type": "string"},
                "svpr_impact": {"type": "string"},
                "exposure": {"type": "string", "enum": ["high", "medium", "low"]},
                "owner": {"type": "string"},
                "action": {"type": "string"},
            },
            "required": ["id", "impact", "svpr_impact", "exposure", "owner", "action"],
            "additionalProperties": False,
        }}},
        "required": ["impacts"],
        "additionalProperties": False,
    }
    by_id = {}
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        payload = [{"id": it["id"], "agency": it.get("agency", ""),
                    "title": it.get("title", ""),
                    "summary": (it.get("summary") or "")[:400]} for it in batch]
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=8000,
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content":
                           f"{_IMPACT_GUIDANCE}\n\n{EMORY_PROFILE}\n\n"
                           f"Items:\n{json.dumps(payload)}"}])
            if resp.stop_reason == "refusal":
                raise RuntimeError("declined")
            text = next(b.text for b in resp.content if b.type == "text")
            for r in json.loads(text)["impacts"]:
                by_id[r["id"]] = r
        except Exception:  # noqa: BLE001
            continue
    out = []
    for it in items:
        item = dict(it)
        r = by_id.get(item["id"])
        if r:
            item["impact"] = r.get("impact", "")
            item["svpr_impact"] = r.get("svpr_impact", "")
            item["exposure"] = r.get("exposure", "")
            item["owner"] = r.get("owner", "")
            item["action"] = r.get("action", "")
        out.append(item)
    return out


# High-severity change types that warrant pulling corroborating news.
_NEWS_TRIGGERS = (
    "terminat", "cancel", "rescind", "rescission", "clawback", "claw back",
    "freeze", "frozen", "stop work", "stop-work", "withdraw", "suspend",
    "disallow", "defund", "budget cut", "funding cut", "eliminat",
)


def enrich_with_news(items: list, max_items: int = 4) -> list:
    """For high-severity disruptive items (cancellations, terminations,
    freezes), have Claude web-search for corroborating coverage/reactions and
    attach a short `news` note plus `news_sources`. Resilient; never raises;
    no-op without an API key. Only the most consequential items are searched
    (cost/latency control)."""
    import re

    import anthropic

    if not claude_available():
        return items

    def qualifies(i):
        if i.get("level") not in ("CRITICAL", "HIGH"):
            return False
        text = f"{i.get('title', '')} {i.get('summary', '')}".lower()
        return any(t in text for t in _NEWS_TRIGGERS)

    targets = [i for i in items if qualifies(i)][:max_items]
    if not targets:
        return items

    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search"}]
    for it in targets:
        prompt = (
            "Search the web for recent news coverage or reactions about this "
            "specific federal research-policy action. Summarize any corroborating "
            "reporting in 1-2 sentences (who reported it, the key point). Then, on a "
            "new line, write 'Sources:' followed by up to 2 source URLs. If you find "
            "no relevant coverage, reply exactly: No additional coverage found.\n\n"
            f"Agency: {it.get('agency', '')}\nTitle: {it.get('title', '')}\n"
            f"Summary: {(it.get('summary') or '')[:400]}")
        messages = [{"role": "user", "content": prompt}]
        try:
            text = ""
            for _ in range(3):  # allow the server-side search loop to resume
                resp = client.messages.create(
                    model=MODEL, max_tokens=1500, tools=tools, messages=messages)
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                if resp.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": resp.content})
                    continue
                break
            if not text or "no additional coverage" in text.lower():
                continue
            urls = re.findall(r"https?://[^\s)\]}>\"']+", text)[:2]
            note = re.split(r"\n?\s*sources?:", text, flags=re.IGNORECASE)[0].strip()
            it["news"] = note[:600]
            it["news_sources"] = urls
        except Exception:  # noqa: BLE001 - news is a bonus, never block delivery
            continue
    return items


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
