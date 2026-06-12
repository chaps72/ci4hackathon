"""Research-relevance filtering.

Federal feeds are noisy: full-text matches on words like "funding" or "grants"
pull in Medicare rules, child-support program notices, etc. This module keeps
items that show genuine research signals and drops benefits-program noise.

Rules, in order:
1. Items from research-only feeds (NIH Guide, NSF News) are always relevant.
2. Items from research agencies (NSF, NIH, NASA, OSTP, ...) are relevant.
3. Grants.gov items are scored on their TITLE only, against strict research
   terms (every Grants.gov summary contains boilerplate like "Funding
   opportunity ...", which must not count as a signal).
4. Other items need research or grant-policy keyword hits, and items dominated
   by excluded program terms (medicare, child support, ...) need strong
   research signals to survive.
"""

# Title patterns that are NEVER government-affairs signal, regardless of
# agency: routine administrative notices that mention research incidentally.
# Checked before every other rule.
VETO_TITLE_MARKERS = [
    # Wildlife/environmental permits (authorize "scientific research" - not policy)
    "endangered species", "endangered wildlife", "recovery permit",
    "incidental take", "marine mammal", "migratory bird", "permit application",
    "receipt of permit",
    # Routine federal advisory committee (FACA) paperwork
    "committee renewal", "charter renewal", "advisory committee",
    "proposal review panel", "notice of meeting", "open meeting",
    "closed meeting", "sunshine act",
    # Paperwork Reduction Act boilerplate
    "agency information collection",
]

# Feeds that only ever carry research content.
TRUSTED_SOURCES = {"NIH Guide", "NSF News"}

# Substrings matched against the agency name (lowercase).
RESEARCH_AGENCY_HINTS = [
    "science foundation",
    "institutes of health",
    "national institute",
    "aeronautics and space",
    "office of science",
    "science and technology policy",
    "advanced research projects",
    "standards and technology",
    "geological survey",
    "oceanic and atmospheric",
]

# Strict research signal terms (stems, matched case-insensitively).
STRONG_RESEARCH_TERMS = [
    "research", "scientific", "scientist", "investigator", "laboratory",
    "university", "universities", "academic", "fellowship", "postdoctoral",
    "doctoral", "peer review", "clinical trial", "biomedical", "stem ",
    "r&d", "research and development", "principal investigator", "nih", "nsf",
    "science", "engineering", "data sharing",
]

# Grant-policy terms: government-wide grants actions affect research funding
# even when the word "research" is absent (e.g., OMB guidance, freezes).
# Counted only for policy sources (Federal Register), NOT for Grants.gov,
# where this language is boilerplate on every opportunity.
GRANT_POLICY_TERMS = [
    "grant program", "grants policy", "uniform guidance", "indirect cost",
    "facilities and administrative", "funding freeze", "public access",
]

# Benefits/administrative program terms that signal non-research content.
EXCLUDE_TERMS = [
    "medicare", "medicaid", "child support", "child care", "foster care",
    "tanf", "temporary assistance for needy families", "snap benefits",
    "supplemental nutrition assistance", "head start", "social security benefit",
    "housing voucher", "section 8", "unemployment insurance",
    "veterans benefits", "workers' compensation", "immigration enforcement",
    "customs", "tariff", "self-sufficiency", "homelessness assistance",
    "refugee resettlement", "victim assistance", "juvenile justice",
]


def research_score(item: dict) -> int:
    if item.get("source") == "Grants.gov":
        # Title only: Grants.gov summaries are generated boilerplate.
        text = (item.get("title") or "").lower()
        terms = STRONG_RESEARCH_TERMS
    else:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        terms = STRONG_RESEARCH_TERMS + GRANT_POLICY_TERMS
    return sum(1 for t in terms if t in text)


def exclusion_hits(item: dict) -> list:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return [t for t in EXCLUDE_TERMS if t in text]


def is_research_relevant(item: dict) -> bool:
    title = (item.get("title") or "").lower()
    if any(m in title for m in VETO_TITLE_MARKERS):
        return False
    if item.get("source") in TRUSTED_SOURCES:
        return True
    agency = (item.get("agency") or "").lower()
    if any(h in agency for h in RESEARCH_AGENCY_HINTS):
        return True
    score = research_score(item)
    if exclusion_hits(item):
        # Benefits-program language present: needs strong research signal to stay.
        return score >= 3
    return score >= 1


def filter_relevant(items: list) -> tuple[list, list]:
    """Split items into (relevant, dropped)."""
    kept, dropped = [], []
    for it in items:
        (kept if is_research_relevant(it) else dropped).append(it)
    return kept, dropped
