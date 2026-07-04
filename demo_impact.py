"""Demo: run Emory-impact analysis on a fixed set of real items, print result."""
import json, os
from fedwatch import summarize

items = [
  {"id":"far","level":"HIGH","date":"2026-06-23","agency":"Office of Management and Budget","source":"Federal Register",
   "title":"FAR Council: Federal Acquisition Regulation Overhaul (E.O. 14275)",
   "summary":"OMB's FAR Council (with DoD, GSA, NASA) proposes a sweeping overhaul of the Federal Acquisition Regulation implementing Executive Order 14275 to eliminate excessive procurement rules. Comment periods open."},
  {"id":"olaw","level":"MODERATE","date":"2026-06-23","agency":"NIH Office of Laboratory Animal Welfare","source":"Federal Register",
   "title":"NIH OLAW: Chimpanzee Research Use Form - 30-Day Comment Request",
   "summary":"NIH's Office of Laboratory Animal Welfare opened a 30-day comment period on its Chimpanzee Research Use Form."},
  {"id":"picap","level":"CRITICAL","date":"2026-06-08","agency":"National Institutes of Health","source":"NIH Guide",
   "title":"RFI: Proposal to Cap the Number of Research Project Grants per Principal Investigator",
   "summary":"NIH seeks input on capping the number of simultaneous Research Project Grants per PI. Responses due August 3, 2026."},
]
out = summarize.analyze_emory_impact(items)
for o in out:
    print(f"\n=== {o['title'][:70]} [{o['level']}] ===")
    print(f"Exposure: {o.get('exposure','?').upper()}")
    print(f"Impact: {o.get('impact','(none)')}")
    print(f"Owner: {o.get('owner','?')}")
    print(f"Action: {o.get('action','?')}")
