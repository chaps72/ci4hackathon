"""SVPR topic domains - the core of relevance.

Derived from what Emory's Office of the SVPR actually tracks on its Federal
Funding and Regulatory Updates page and the RCRA compliance portfolio:
indirect cost actions (and their litigation status), foreign subawards and
research security, award terminations/appeals, executive orders and agency
implementation guidance, grants policy, compliance regimes, and the federal
budget outlook.

An item is relevant if it matches at least one domain. Matches are tagged so
the feed can show WHY an item is in.
"""

DOMAINS = {
    "Indirect costs & funding caps": [
        "indirect cost", "facilities and administrative", "f&a rate",
        "salary cap", "pi cap", "per principal investigator", "cap the number",
        "grants per pi", "payline", "15% indirect", "negotiated rate",
    ],
    "Terminations, freezes & closeout": [
        "terminat", "funding freeze", "freeze on", "stop work", "stop-work",
        "closeout", "rescission", "rescind", "withhold", "suspension of award",
        "award suspension", "disallow",
    ],
    "Executive actions": [
        "executive order", "presidential memorandum", "presidential proclamation",
        "presidential document",
    ],
    "Grants policy & uniform guidance": [
        "uniform guidance", "2 cfr 200", "grants policy", "prior approval",
        "federal financial assistance", "notice of award", "award conditions",
        "foreign subaward", "subaward structure",
    ],
    "Research security & foreign influence": [
        "research security", "foreign influence", "foreign component",
        "foreign talent", "nspm-33", "other support", "disclosure requirement",
        "fundamental research security", "covered institution",
    ],
    "Export controls & visas": [
        "export control", "deemed export", "itar", "export administration",
        "visa", "exchange visitor", "j-1", "h-1b",
    ],
    "Human subjects & clinical research": [
        "human subjects", "common rule", "institutional review board",
        "clinical trial", "clinical research", "inclusion of women",
        "informed consent", "45 cfr 46",
    ],
    "Animal research": [
        "animal welfare", "vertebrate animal", "iacuc", "primate", "olaw",
        "laboratory animal",
    ],
    "Biosafety & biosecurity": [
        "select agent", "biosafety", "dual use", "durc", "gain-of-function",
        "pathogen oversight",
    ],
    "Research integrity & misconduct": [
        "research misconduct", "research integrity", "scientific integrity",
        "office of research integrity", "plagiarism", "falsification",
    ],
    "Data, publications & privacy": [
        "data sharing", "public access", "data management", "genomic data",
        "scientific data", "human research protections",
    ],
    "Budget & appropriations": [
        "appropriation", "continuing resolution", "budget request",
        "authorization act", "rescission package", "omnibus", "fiscal outlook",
        "budget cut",
    ],
    "Peer review & research workforce": [
        "peer review", "study section", "fellowship policy", "training grant",
        "postdoctoral", "early career", "simplified review",
    ],
}

# Severity defaults per domain (classify keyword rules can still escalate).
DOMAIN_BASE_LEVEL = {
    "Indirect costs & funding caps": "CRITICAL",
    "Terminations, freezes & closeout": "CRITICAL",
    "Executive actions": "CRITICAL",
    "Grants policy & uniform guidance": "HIGH",
    "Research security & foreign influence": "HIGH",
    "Export controls & visas": "HIGH",
    "Human subjects & clinical research": "HIGH",
    "Animal research": "HIGH",
    "Biosafety & biosecurity": "HIGH",
    "Research integrity & misconduct": "HIGH",
    "Data, publications & privacy": "MODERATE",
    "Budget & appropriations": "HIGH",
    "Peer review & research workforce": "MODERATE",
}


def match_domains(item: dict) -> list:
    """Return the list of SVPR domains the item touches."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return [d for d, phrases in DOMAINS.items() if any(p in text for p in phrases)]


def base_level(domains: list) -> str:
    """Most severe base level across matched domains (INFO when none)."""
    order = ["CRITICAL", "HIGH", "MODERATE", "INFO"]
    levels = [DOMAIN_BASE_LEVEL.get(d, "INFO") for d in domains]
    return min(levels, key=order.index) if levels else "INFO"
