"""Criticality classification for federal research updates.

Keyword-rule based so it works offline and is easy for the team to tune.
Levels, highest to lowest: CRITICAL, HIGH, MODERATE, INFO.
"""

from dataclasses import dataclass, field

LEVELS = ["CRITICAL", "HIGH", "MODERATE", "INFO"]

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
    ],
    "HIGH": [
        "deadline", "final rule", "effective date", "compliance", "new requirement",
        "must submit", "indirect cost", "salary cap", "policy change", "prior approval",
        "certification", "disclosure", "foreign influence", "security review",
        "expiration", "closing date",
    ],
    "MODERATE": [
        "notice of funding opportunity", "nofo", "foa", "funding opportunity",
        "proposed rule", "comment period", "request for information", "rfi",
        "request for comment", "draft guidance", "listening session",
    ],
}


@dataclass
class Classifier:
    rules: dict = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_RULES.items()})
    # Team watchlist: any hit bumps the item at least to HIGH and tags it.
    watchlist: list = field(default_factory=list)

    def classify(self, item: dict) -> dict:
        """Return the item with `level`, `matched_keywords`, and `watchlist_hits` set."""
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

        matched = []
        level = "INFO"
        for lvl in ("CRITICAL", "HIGH", "MODERATE"):
            hits = [kw for kw in self.rules.get(lvl, []) if kw.lower() in text]
            if hits and level == "INFO":
                level = lvl
            matched.extend(hits)

        watch_hits = [w for w in self.watchlist if w and w.lower() in text]
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
