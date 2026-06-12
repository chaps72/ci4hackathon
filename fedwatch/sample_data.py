"""Bundled sample updates so the app works offline / before APIs are configured.

Items mirror the shape returned by fedwatch.sources fetchers:
    id, source, agency, title, summary, url, date (YYYY-MM-DD), type
"""

SAMPLE_ITEMS = [
    {
        "id": "sample-001",
        "source": "Federal Register",
        "agency": "Office of Management and Budget",
        "title": "Guidance on Temporary Pause of Agency Grant Programs Pending Review",
        "summary": "OMB directs agencies to identify grant programs subject to a temporary funding freeze "
                   "while compliance with recent executive order requirements is reviewed. Agencies must "
                   "report affected programs immediately.",
        "url": "https://www.federalregister.gov/",
        "date": "2026-06-10",
        "type": "Notice",
    },
    {
        "id": "sample-002",
        "source": "NIH Guide",
        "agency": "National Institutes of Health",
        "title": "Notice of Changes to NIH Salary Cap and Indirect Cost Rate Policies for FY2027",
        "summary": "NIH announces a revised salary cap effective October 1 and new requirements for "
                   "indirect cost rate negotiation. Institutions must submit updated rate agreements "
                   "before the effective date to avoid award delays.",
        "url": "https://grants.nih.gov/grants/guide/",
        "date": "2026-06-09",
        "type": "Policy Notice",
    },
    {
        "id": "sample-003",
        "source": "Grants.gov",
        "agency": "National Science Foundation",
        "title": "NOFO: Mid-scale Research Infrastructure-2 (Mid-scale RI-2)",
        "summary": "New notice of funding opportunity for research infrastructure projects between $20M "
                   "and $100M. Preliminary proposals due September 2026.",
        "url": "https://www.grants.gov/",
        "date": "2026-06-08",
        "type": "Funding Opportunity",
    },
    {
        "id": "sample-004",
        "source": "Federal Register",
        "agency": "Department of Health and Human Services",
        "title": "Final Rule: Research Security Disclosure Requirements for Federally Funded Investigators",
        "summary": "HHS issues a final rule requiring expanded disclosure of foreign affiliations and "
                   "outside support for all senior/key personnel on federally funded research. "
                   "Compliance required by January 2027.",
        "url": "https://www.federalregister.gov/",
        "date": "2026-06-06",
        "type": "Rule",
    },
    {
        "id": "sample-005",
        "source": "NSF News",
        "agency": "National Science Foundation",
        "title": "NSF Releases Annual Merit Review Report",
        "summary": "NSF publishes its annual report on the merit review process, including funding rates "
                   "by directorate and demographic data on proposers.",
        "url": "https://www.nsf.gov/news/",
        "date": "2026-06-05",
        "type": "Report",
    },
    {
        "id": "sample-006",
        "source": "Federal Register",
        "agency": "Office of Science and Technology Policy",
        "title": "Request for Information: Implementation of Public Access Requirements for Federally Funded Research",
        "summary": "OSTP seeks public comment on agency plans for immediate public access to peer-reviewed "
                   "publications and supporting data. Comment period closes August 15, 2026.",
        "url": "https://www.federalregister.gov/",
        "date": "2026-06-04",
        "type": "RFI",
    },
    {
        "id": "sample-007",
        "source": "NIH Guide",
        "agency": "National Institutes of Health",
        "title": "Notice of Early Termination of Select Research Project Grants Following Program Review",
        "summary": "NIH provides notice that certain awards under review will be terminated effective "
                   "30 days from this notice. Affected institutions will receive individual stop-work "
                   "instructions from their grants management specialist.",
        "url": "https://grants.nih.gov/grants/guide/",
        "date": "2026-06-03",
        "type": "Notice",
    },
    {
        "id": "sample-008",
        "source": "Grants.gov",
        "agency": "Department of Energy",
        "title": "NOFO: Office of Science Early Career Research Program FY2027",
        "summary": "DOE announces the FY2027 Early Career Research Program. Pre-applications due "
                   "October 2026; full applications by invitation only.",
        "url": "https://www.grants.gov/",
        "date": "2026-06-02",
        "type": "Funding Opportunity",
    },
    {
        "id": "sample-009",
        "source": "Federal Register",
        "agency": "National Institutes of Health",
        "title": "Proposed Rule: Simplified Review Framework for NIH Research Project Grant Applications",
        "summary": "NIH proposes changes to the peer review criteria framework. A 60-day comment period "
                   "is open; institutions are encouraged to coordinate institutional responses.",
        "url": "https://www.federalregister.gov/",
        "date": "2026-06-01",
        "type": "Proposed Rule",
    },
    {
        "id": "sample-010",
        "source": "NSF News",
        "agency": "National Science Foundation",
        "title": "Reminder: Research.gov Submission Deadline for CAREER Proposals July 23",
        "summary": "NSF reminds the community that the CAREER program closing date is July 23, 2026, "
                   "5 p.m. submitter's local time. No extensions will be granted.",
        "url": "https://www.nsf.gov/news/",
        "date": "2026-05-30",
        "type": "Reminder",
    },
    {
        "id": "sample-011",
        "source": "Federal Register",
        "agency": "Executive Office of the President",
        "title": "Executive Order: Strengthening Oversight of Federally Funded Research Institutions",
        "summary": "Executive order directing agencies to review institutional compliance programs and "
                   "establish new certification requirements for institutions receiving more than $50M "
                   "in annual federal research funding.",
        "url": "https://www.federalregister.gov/",
        "date": "2026-05-29",
        "type": "Presidential Document",
    },
    {
        "id": "sample-012",
        "source": "NIH Guide",
        "agency": "National Institutes of Health",
        "title": "NIH Virtual Seminar on Grants Administration Registration Open",
        "summary": "Registration is now open for the NIH Virtual Seminar on Program Funding and Grants "
                   "Administration, to be held November 2026.",
        "url": "https://grants.nih.gov/grants/guide/",
        "date": "2026-05-28",
        "type": "Announcement",
    },
]
