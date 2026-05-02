# Linden Decision Memo: Import and Automation Priorities

Date: 2026-05-01
Owner: Product Strategy
Status: Proposed

## Decision
Linden should prioritize **connected document import** as the next major automation investment after contact import.

Recommended order:

1. finish and broaden contact import
2. ship Google Drive and Gmail document import
3. add insurance extraction and linking
4. add Plaid-based financial account inventory
5. add password-manager inventory
6. add vehicle and real-estate enrichment

## Why This Decision
Linden's strongest category opportunity is not "more integrations."

It is:

**help families connect the records they already have, detect what is missing or stale, and stay ready before a crisis happens.**

Connected document import is the best next step because it:

- reduces setup friction immediately
- maps directly to the existing file and reminder model
- supports later drift detection
- strengthens the readiness story more than a generic onboarding feature would

## Why Documents Come Before Password Managers
1Password and Bitwarden integrations are useful, but they should not be the next headline feature.

Reasons:

- document import is relevant to a larger share of families than password-manager import
- wills, policies, IDs, deeds, and statements already exist in email and cloud drives
- imported documents feed multiple downstream workflows: classification, reminders, entity linking, and gap detection
- password-manager integrations create higher trust and security expectations

The right framing for password-manager integrations is:

**digital access inventory**

That is strategically sound, but it should follow after Linden proves the connected-records workflow on documents.

## What We Are Optimizing For
The priority sequence should maximize:

- time-to-value for new users
- completeness of important family records
- future readiness and drift-detection value
- reuse of the existing OAuth and async import architecture

## What We Are Not Doing
Linden should not optimize for:

- the largest possible integrations catalog
- becoming a password manager
- becoming a budgeting app
- importing data with no review or user control

## Success Criteria
This strategy is working if:

- users can connect a source and import meaningful records in minutes
- imported records reduce manual data entry materially
- imported files and records become reminders, links, and readiness signals
- the product can explain what was imported, what was skipped, and what still needs attention

## Product Guardrails
Every import feature should answer one question:

**Does this make Linden better at detecting family, estate, access, or document drift?**

If not, it is probably not worth shipping.

## Immediate Next Step
Build a first connected document import flow for US users using Google sources:

- Google Drive files
- Gmail attachments

The first release should import selected files into Linden, classify them, and store source metadata so later product work can turn them into reminders, links, and drift signals.
