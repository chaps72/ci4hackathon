# FedWatch — Federal Research Updates Awareness Tool

Internal Streamlit dashboard that keeps the team aware of federal research policy
and funding updates from government sources, with criticality-level notifications,
executive summaries, and email-safe digests.

## What it does

- **Pulls live updates** from:
  - Federal Register API (rules, notices, executive orders related to research funding)
  - Grants.gov Search2 API (new funding opportunities)
  - NIH Guide RSS (notices and funding opportunities)
  - NSF News RSS
  - **NIH RePORTER API** (funded NIH/HHS awards) — see the weekly award report below.
  - Falls back to bundled sample data when feeds are unreachable, so the demo always works.
- **NIH RePORTER weekly award report** (its own tab): pulls recently issued NIH awards
  straight from the live [NIH RePORTER API](https://api.reporter.nih.gov/) (no key
  required). Toggle between **your institution's new awards** (defaults to Emory) and a
  **topic/keyword search across all institutions**. Shows funding totals, per-institute
  counts, per-award detail, CSV export, an AI/template-written summary, and a downloadable
  `.eml` digest. Fails soft to bundled sample awards when the API is unreachable.
- **Classifies every item by criticality level**: 🔴 Critical, 🟠 High, 🟡 Moderate, 🔵 Info —
  using transparent, editable keyword rules. A team **watchlist** (e.g., "indirect cost",
  "salary cap") bumps matching items to at least HIGH and flags them.
- **Notification feed** with unread tracking, level/agency/source filters, and CSV export.
- **Summaries**: executive summary for leadership, team digest, or one-paragraph brief.
  Uses the Claude API (`claude-opus-4-8`) when `ANTHROPIC_API_KEY` is set; otherwise a
  built-in template engine generates a structured summary so the app works without a key.
- **Email-safe digests**: HTML + plain text + downloadable `.eml`. All feed content is
  HTML-escaped (no injection from upstream sources), links restricted to http(s), inline
  styles only — no scripts, external images, or tracking pixels.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # optional, enables AI-written summaries
streamlit run fedwatch_app.py
```

The **NIH RePORTER Weekly Report** is also available as its own standalone app
(same data, no FedWatch dashboard around it): `streamlit run nih_reporter_app.py`.

The original Trial & Sample Finder app remains available: `streamlit run main.py`.

## Project layout

```
fedwatch_app.py          Streamlit dashboard (feed / summaries / email tabs)
fedwatch/
  sources.py             Fetchers for Federal Register, Grants.gov, NIH, NSF (fail-soft)
  reporter.py            NIH RePORTER award fetcher + aggregates for the weekly report
  classify.py            Keyword-rule criticality classifier + watchlist
  summarize.py           Claude API summaries with template fallback
  emailer.py             Sanitized HTML / plain-text / .eml digest builder
  sample_data.py         Offline sample dataset
```

## Ideas for next steps

- Scheduled fetch + Slack/Teams webhook notifications for CRITICAL items
- Persist read-state and watchlist to a small database (currently per-session)
- More sources: agency-specific NOFO feeds, regulations.gov dockets, OMB memos
- Per-user subscriptions (only notify me about NIH + DOE items)
