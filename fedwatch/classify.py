"""Criticality classification for federal research updates.

Keyword-rule based so it works offline and is easy for the team to tune.
Levels, highest to lowest: CRITICAL, HIGH, MODERATE, INFO.
"""

from dataclasses import dataclass, field

LEVELS = ["CRITICAL", "HIGH", "MODERATE", "INFO"]

# Built-in watched terms: dedicated 90-day Federal Register search, never
# filtered out, rank at least HIGH.
DEFAULT_WATCHLIST = ["indirect cost", "salary cap", "grant cap", "pi cap",
                     "per principal investigator"]

LEVEL_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "MODERATE": "🟡",
    "INFO": "🔵",
}

LEVEL_DESCRIPTIONS = {
    "CRITICAL": "Immediate action or major disruption: terminations, funding freezes, rescissions, stop-work orders.",
    "HIGH": "Action likely required: new compliance requirements, final rules, deadlines, policy changes.",
    "MODERATE": "Worth tracking: funding opportunities, proposed rules, comment periods, RFIs.",
    "INFO": "General awareness: announcements, reports, routine notices.",
}

# Default keyword rules. Matched case-insensitively against title + summary.
# Stems are used on purpose ("terminat" matches terminate/terminated/termination).
DEFAULT_RULES = {
    "CRITICAL": [
        "terminat", "rescind", "rescission", "suspend", "stop work", "stop-work",
        "funding freeze", "freeze on", "immediately", "executive order",
        "cancell", "withdrawn", "revoked", "shutdown", "halt",
        "salary cap", "pi cap", "per principal investigator", "cap the number",
        "grants per pi", "unified funding strategy",
    ],
    "HIGH": [
        "deadline", "final rule", "effective date", "compliance", "new requirement",
        "must submit", "indirect cost", "policy change", "prior approval",
        "certification", "disclosure", "foreign influence", "security review",
        "expiration", "closing date",
        # Biomedical-heavy portfolio (Emory): these regimes matter
        "human subjects", "common rule", "clinical trial", "animal welfare",
        "select agent", "biosafety", "dual use", "institutional review board",
        "vertebrate animals", "primate",
    ],
    "MODERATE": [
        "notice of funding opportunity", "nofo", "foa", "funding opportunity",
        "proposed rule", "comment period", "request for information", "rfi",
        "request for comment", "draft guidance", "listening session",
    ],
}

# Agencies whose items are always treated as CRITICAL: government-wide
# directives (e.g., OMB) move fast and hit every award. Matched loosely
# because feeds vary the phrasing ("Office of Management and Budget",
# "Management and Budget Office", ...).
CRITICAL_AGENCY_HINTS = [
    "management and budget",
    "executive office of the president",
    "office of the president",
]


@dataclass
class Classifier:
    rules: dict = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_RULES.items()})
    # Team watchlist: any hit bumps the item at least to HIGH and tags it.
    watchlist: list = field(default_factory=list)

    def classify(self, item: dict) -> dict:
        """Return the item with `level`, `matched_keywords`, and `watchlist_hits` set."""
        import re

        def kw_in(kw: str, text: str) -> bool:
            # Word-boundary prefix match: "terminat" matches "termination"
            # but not "determination".
            return re.search(r"\b" + re.escape(kw.lower()), text) is not None

        title = (item.get("title") or "").lower()
        text = f"{title} {item.get('summary', '')}".lower()

        matched = []
        level = "INFO"
        agency = (item.get("agency") or "").lower()
        if any(h in agency for h in CRITICAL_AGENCY_HINTS) or re.search(r"\bomb\b", title):
            level = "CRITICAL"
            matched.append(f"agency:{item.get('agency') or 'OMB'}")

        # CRITICAL keywords must appear in the TITLE - regulatory summaries
        # mention words like "withdrawn" or "suspended" incidentally, which
        # caused false criticals. A summary-only critical hit caps at HIGH.
        crit_title = [kw for kw in self.rules.get("CRITICAL", []) if kw_in(kw, title)]
        crit_summary = [kw for kw in self.rules.get("CRITICAL", []) if kw_in(kw, text) and kw not in crit_title]
        if crit_title and level == "INFO":
            level = "CRITICAL"
        matched.extend(crit_title)

        for lvl, extra in (("HIGH", crit_summary), ("MODERATE", [])):
            hits = [kw for kw in self.rules.get(lvl, []) if kw_in(kw, text)] + extra
            if hits and level == "INFO":
                level = lvl
            matched.extend(hits)

        watch_hits = [w for w in self.watchlist if w and kw_in(w, text)]
        if watch_hits and LEVELS.index(level) > LEVELS.index("HIGH"):
            level = "HIGH"

        out = dict(item)
        out["level"] = level
        out["matched_keywords"] = matched
        out["watchlist_hits"] = watch_hits
        return out

    def classify_all(self, items: list) -> list:
        return [self.classify(i) for i in items]


def level_counts(items: list) -> dict:
    counts = {lvl: 0 for lvl in LEVELS}
    for i in items:
        counts[i.get("level", "INFO")] = counts.get(i.get("level", "INFO"), 0) + 1
    return counts


def sort_by_priority(items: list) -> list:
    return sorted(
        items,
        key=lambda i: (LEVELS.index(i.get("level", "INFO")), i.get("date", "")),
    )
