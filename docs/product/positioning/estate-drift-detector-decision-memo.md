# Linden Decision Memo: Estate Drift Detector

Date: 2026-05-01
Owner: Product Strategy
Status: Proposed

## Decision
Linden should productize the **Estate Drift Detector** as the first sharp expression of its broader family continuity positioning.

Recommended v1 scope:

1. account-level readiness brief
2. 8-12 high-confidence drift detectors
3. plain-language findings
4. one-click todo generation
5. will summary generation

## Why This Decision
Linden should not compete as:

- a chatbot
- a generic AI assistant
- another digital vault

The strongest category territory is:

**the system that detects when a family's plans, access, documents, and responsibilities have drifted out of sync with real life, then tells them what to fix next.**

This is stronger because it is:

- more specific than "AI for families"
- more defensible than storage alone
- already grounded in Linden's existing data model
- already partially supported by the health system

## Why This Comes Through Product, Not Just Messaging
The idea only works if users can see it happening in the product.

That means Linden needs to move beyond passive records and expose:

- what is missing
- what is stale
- what is risky
- what action should happen next

The health system already computes readiness scores and missing checks. The next step is to turn that machinery into a user-facing findings product.

## What We Are Optimizing For
The v1 should maximize:

- perceived preparedness value
- explainability and trust
- actionability over novelty
- reuse of current structured data and health evaluators

## What We Are Not Doing
The first release should not try to be:

- open-ended chat
- autonomous legal or financial advice
- a heavy document-interpretation workflow
- a giant rule engine spanning every Linden entity on day one

## Product Guardrails
The detector should:

- start with deterministic, explainable checks
- use AI only to explain, summarize, and rank
- link every finding to concrete records
- create actions, not just warnings

The detector should not:

- invent unsupported facts
- hide why a finding exists
- present vague, generic wellness-style advice

## Why This Is the Right Wedge
Most competitors are easier to describe, but weaker to defend:

- vault
- will creator
- checklist
- advisor workspace

Linden's wedge is better if it owns:

- cross-entity drift detection
- risk prioritization
- continuity readiness
- action orchestration

## Success Criteria
This strategy is working if:

- users understand why their readiness score changed
- findings feel specific and credible
- findings produce actual follow-up tasks
- the product helps users resolve meaningful gaps faster

## Immediate Next Step
Ship a narrow v1 as a health-system extension:

- compute drift findings from existing structured checks
- expose a readiness brief and ranked findings
- allow one-click todo generation from findings
- optionally generate plain-language will summaries where source data exists

The main implementation bet is not "more AI."

It is:

**turn the current health and planning graph into a clear, actionable readiness layer.**
