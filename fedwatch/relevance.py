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

# Agencies that never produce SVPR-relevant research policy. Their documents
# match the research-terms query incidentally (wildlife "scientific research"
# permits, poultry inspection studies, firearms/conservation rules).
VETO_AGENCY_HINTS = [
    "fish and wildlife", "marine fisheries", "park service", "land management",
    "forest service", "reclamation", "alcohol, tobacco", "firearms",
    "food safety and inspection", "animal and plant health inspection",
    "agricultural marketing", "coast guard", "mine safety",
    "transportation safety", "surface transportation", "fishery",
    "aviation", "transportation department", "department of transportation",
]

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
    # Topic areas with no relation to the research portfolio
    "firearm", "hunting", "poultry", "livestock", "fisheries", "fishery",
    "grazing", "timber", "meat and", "conservation plan", "wildlife refuge",
    "restricted area", "airspace", "public lands", "realty",
    "coal combustion", "solid waste", "hazardous waste",
    # High-volume routine NIH/agency notices that drown the feed
    "patent license", "exclusive license", "government-owned invention",
    "prospective grant of",
]

# Feeds that only ever carry research content.
TRUSTED_SOURCES = {"NIH Guide", "NSF News"}

# Agencies relevant to Emory's portfolio (SVPR scope): NIH/HHS biomedical,
# NSF, DOE, DOD research arms, NASA, and government-wide policy offices.
# Matched as substrings of the agency name (feeds vary word order:
# "Energy Department" vs "Department of Energy").
RESEARCH_AGENCY_HINTS = [
    "institutes of health",
    "science foundation",
    "science and technology policy",
    "advanced research projects",       # DARPA, ARPA-H, ARPA-E
    "department of energy", "energy depart",
    "department of defense", "defense depart",
    "army research", "naval research", "air force research",
    "aeronautics and space",            # NASA
    "centers for disease control",
    "agency for healthcare research",
    "food and drug administration",
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


def _vetoed(item: dict) -> bool:
    title = (item.get("title") or "").lower()
    if any(m in title for m in VETO_TITLE_MARKERS):
        return True
    agency = (item.get("agency") or "").lower()
    return any(h in agency for h in VETO_AGENCY_HINTS)


# Government-wide policy offices (OMB, EOP): publish on every topic -
# DHS operations, cybersecurity logging, procurement, discount rates - so
# they are NOT blanket-relevant. Their items must touch the research
# enterprise. (Once relevant, classify still ranks them CRITICAL.)
GOV_WIDE_AGENCY_HINTS = [
    "management and budget",
    "executive office of the president",
    "office of the president",
]
GOV_WIDE_TOPIC_TERMS = [
    "research", "grant", "science", "r&d", "universit", "higher education",
    "indirect cost", "uniform guidance", "federal financial assistance",
    "funding", "appropriation", "rescission", "salary cap",
]


def is_research_relevant(item: dict) -> bool:
    """STRICT whitelist: an item is relevant only if it comes from a research
    feed/agency, or carries explicit research-policy language in its TITLE.

    Blacklisting noise topics one by one proved endless - each day's Federal
    Register surfaces new irrelevant families. Whitelisting is the durable fix.
    """
    # Pinned tracked notices are never filtered, period.
    if item.get("type") == "Tracked Notice":
        return True
    # Watchlist-targeted items skip relevance scoring but NOT the vetoes -
    # generic watch terms match airspace/public-lands/hunting documents.
    if item.get("watchlist_targeted"):
        return not _vetoed(item)
    if _vetoed(item):
        return False
    if item.get("source") in TRUSTED_SOURCES:
        return True
    agency = (item.get("agency") or "").lower()
    if any(h in agency for h in RESEARCH_AGENCY_HINTS):
        return True
    title = (item.get("title") or "").lower()
    if any(h in agency for h in GOV_WIDE_AGENCY_HINTS):
        # OMB/EOP: relevant only when the action touches research/grants.
        text = f"{title} {item.get('summary', '')}".lower()
        return any(t in text for t in GOV_WIDE_TOPIC_TERMS)
    # Everything else must say so in the TITLE.
    title_hits = [t for t in STRONG_RESEARCH_TERMS + GRANT_POLICY_TERMS if t in title]
    if not title_hits:
        return False
    if any(t in title for t in EXCLUDE_TERMS):
        return False
    return True


def filter_relevant(items: list) -> tuple[list, list]:
    """Split items into (relevant, dropped)."""
    kept, dropped = [], []
    for it in items:
        (kept if is_research_relevant(it) else dropped).append(it)
    return kept, dropped
