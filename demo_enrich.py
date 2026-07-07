"""Demo: SVPR-office impact + web-sourced news on realistic items."""
from fedwatch import summarize
from fedwatch.classify import LEVELS

items = [
  {"id":"term","level":"CRITICAL","agency":"National Institutes of Health","source":"NIH Guide",
   "title":"Notice of Termination of Certain Research Project Grants Following Program Review",
   "summary":"NIH provides notice that certain awards under review will be terminated effective 30 days from this notice."},
  {"id":"cap","level":"CRITICAL","agency":"National Institutes of Health","source":"NIH Guide",
   "title":"RFI: Proposal to Cap the Number of Research Project Grants per Principal Investigator",
   "summary":"NIH seeks input on capping simultaneous RPGs per PI. Responses due August 3, 2026."},
]
items = summarize.analyze_emory_impact(items)
items = summarize.enrich_with_news(items)
for it in items:
    print(f"\n=== [{it['level']}] {it['title'][:65]} ===")
    print(f"SVPR office: {it.get('svpr_impact','(none)')}")
    print(f"Severity: {it.get('exposure','?')} | Owner: {it.get('owner','?')} | Action: {it.get('action','?')}")
    if it.get("news"):
        print(f"IN THE NEWS: {it['news']}")
        print(f"Sources: {it.get('news_sources')}")
    else:
        print("IN THE NEWS: (none found / not triggered)")
