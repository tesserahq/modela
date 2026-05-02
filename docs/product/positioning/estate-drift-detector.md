## Linden Positioning: Estate Drift Detector

Research date: 2026-04-30

### Core Thesis
Linden should not position itself as a chatbot, generic AI assistant, or another digital vault.

The stronger territory is:

**Linden is the system that detects when a family's plans, assets, documents, access, and wishes have drifted out of sync with real life, then tells them exactly what to fix next.**

That idea is more defensible because it maps directly to Linden's current data model:

- family members and relationships
- wills and will parties
- emergency access memberships
- online accounts
- insurance coverage
- reminders
- todo lists
- legacy messages
- body and memorial wishes
- advisor contacts
- share links
- health scores and missing checks

Relevant code seams:

- [docs/architecture/health-system.md](/Users/emiliano.jankowski/sites/linden-family/linden-api/docs/architecture/health-system.md:1)
- [app/health/evaluators/account.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/health/evaluators/account.py:1)
- [app/health/evaluators/person.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/health/evaluators/person.py:1)
- [app/models/membership.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/models/membership.py:1)
- [app/models/will.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/models/will.py:1)
- [app/models/will_party.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/models/will_party.py:1)
- [app/models/legacy_message.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/models/legacy_message.py:1)
- [app/models/body_memorial_wishes.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/models/body_memorial_wishes.py:1)
- [app/models/todo_list.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/models/todo_list.py:1)
- [app/schemas/context_pack.py](/Users/emiliano.jankowski/sites/linden-family/linden-api/app/schemas/context_pack.py:1)

### Category
Recommended category language:

- **Family Continuity Intelligence**
- **Life & Legacy Readiness System**
- **Estate Drift Detection**

Recommended primary category:

**Family Continuity Intelligence**

Recommended product wedge:

**Estate Drift Detector**

Why this pairing works:

- "Family Continuity Intelligence" is broad enough for the company vision.
- "Estate Drift Detector" is specific enough to feel new, sharp, and legible.
- It avoids sounding like a legal form generator or a generic AI wrapper.

### Positioning Statement
**Linden is the only family continuity platform that detects when your plans, access, and important records have fallen out of sync with real life, so your family knows what to fix before a crisis happens.**

Alternative shorter version:

**Linden helps families spot plan drift early and stay prepared through life's hardest transitions.**

### Who This Is For
Primary audience:

- adults managing family responsibilities
- parents with dependents
- people coordinating aging-parent or multigenerational responsibilities
- households with legal, insurance, property, and digital-account complexity

Secondary audience:

- executors
- attorneys
- financial advisors
- care coordinators

### Competitive Difference
Most competitors cluster in one of these positions:

- document vault
- will/trust creator
- guidance checklist
- advisor or benefits distribution tool

Linden should instead own:

- cross-entity detection
- risk prioritization
- preparedness orchestration
- continuity across family, advisors, and critical transitions

This is meaningfully different from:

- Trustworthy: broad family operating system
- Everplans: guided organization
- GoodTrust / Gentreo / Trust & Will: estate-plan-first
- Empathy LifeVault: institution-led legacy planning

### Messaging Pillars
#### 1. Detect Drift
Life changes. Estate plans usually do not.

Linden should emphasize that the real problem is not just missing documents. It is misalignment between:

- people and roles
- assets and coverage
- wishes and access
- plans and current reality

#### 2. Prioritize What Matters
Families do not need more folders. They need clarity on what matters now.

Linden should surface:

- highest-risk gaps
- time-sensitive issues
- blocked handoffs
- outdated records

#### 3. Turn Complexity Into Action
The product should not stop at insight. It should create the next step.

Examples:

- generate a todo list
- propose who should be invited
- flag which document needs review
- explain in plain language why an issue matters

#### 4. Preserve Trust
AI should feel precise, bounded, and privacy-safe.

The product promise is not "talk to an AI."
The promise is "Linden quietly helps you stay prepared."

### Homepage Copy
#### Hero Options
Option A:

**Life changes fast. Your plan should keep up.**

Linden detects when your family records, wishes, access, and estate plans fall out of sync, then shows you exactly what to fix before it becomes a crisis.

Option B:

**The system that tells families what they're missing before it matters most.**

Linden turns scattered documents and outdated plans into clear next steps, so the right people can act when life gets complicated.

Option C:

**Not just a vault. A way to catch plan drift before your family pays for it.**

Linden watches for missing access, stale wishes, incomplete records, and unshared responsibilities across the people and assets your family depends on.

#### Supporting Section Copy
**Most families don't fail because they forgot to upload a file. They fail because life changed and no one updated the plan.**

Linden helps you stay aligned across wills, trusted contacts, insurance, digital accounts, important documents, and final wishes. When something is missing, outdated, or contradictory, Linden surfaces it and helps you act.

#### Three Feature Blocks
**Detect what drifted**

Linden spots missing roles, outdated documents, coverage gaps, and access problems across your family records.

**Know what matters now**

Not every gap is urgent. Linden prioritizes what actually puts your family at risk.

**Turn insight into action**

Generate clear follow-ups, assign tasks, and keep trusted people in the loop without oversharing everything.

#### Trust / AI Section
**AI that prepares, not distracts**

Linden uses AI to analyze your family's planning data, surface gaps, and explain next steps in plain language. It is designed to support decisions, not replace them.

### Product Concept
## Estate Drift Detector

### Product Summary
A system that analyzes structured household data and detects where a family's plans, records, permissions, and responsibilities are incomplete, outdated, or contradictory.

It should feel like:

- readiness intelligence
- risk detection
- planning coordination

It should not feel like:

- open-ended chat
- vague life coaching
- generic document summarization

### v1 Product Goal
Produce a useful, trusted, actionable "readiness and drift" layer using current structured data before introducing heavier generative features.

### v1 User Promise
**Linden tells you what is missing, what is stale, what is risky, and what to do next.**

## v1 Feature Spec
### 1. Drift Types
The first version should detect a small set of high-confidence drift patterns.

#### A. Access Drift
The right person is named, but cannot act.

Examples:

- a will has an executor, but that person does not have account access
- the account has critical information, but fewer than two members have `emergency_access`
- a shareable link exists for a resource that should probably be shared more durably through membership or advisor access

Current data support:

- memberships with `emergency_access`
- will parties
- invitations
- share links

#### B. Coverage Drift
Important people or assets exist, but supporting protection is missing or unclear.

Examples:

- a person exists without life or health insurance coverage
- a vehicle or real estate asset exists without corresponding insurance
- a will exists without a document or without a plain-language summary

Current data support:

- insurance policies
- insurance covered entities
- vehicles
- real estate
- wills

#### C. Role Drift
The family graph changed, but responsibility mapping did not.

Examples:

- there are dependents or family members, but no guardian or executor relationships have been captured
- an attorney is listed for a will, but no advisor contact exists at the account level
- a person has memorial wishes or legacy messages missing while other planning artifacts exist

Current data support:

- persons
- will parties
- contacts
- body memorial wishes
- legacy messages

#### D. Freshness Drift
Information exists but is probably outdated or incomplete.

Examples:

- documents nearing expiry
- reminders missing for critical documents
- wills with old issuance dates and no recent review signal
- online accounts present without sufficient supporting notes or recovery details

Current data support:

- reminders
- passports
- driver's licenses
- wills
- online accounts

### 2. Detector Output
Each detected issue should generate a structured finding with:

- `finding_type`
- `severity`
- `title`
- `explanation`
- `affected_entities`
- `recommended_actions`
- `confidence`

Example:

```json
{
  "finding_type": "access_drift",
  "severity": "high",
  "title": "Your executor may not be able to act",
  "explanation": "A will names an executor, but Linden cannot find an active account member with matching access.",
  "affected_entities": [
    {"type": "will", "id": "uuid"},
    {"type": "person", "id": "uuid"}
  ],
  "recommended_actions": [
    "Invite the executor to the account",
    "Grant emergency access if appropriate",
    "Confirm the executor email matches the current contact details"
  ],
  "confidence": 0.94
}
```

### 3. Product Surfaces
#### A. Account Readiness Brief
A top-level summary for the account:

- overall readiness score
- top 3 highest-priority findings
- actions to complete this month

This should extend the existing health model rather than replace it.

#### B. Entity-Level Warnings
Attach findings to:

- person
- will
- insurance
- vehicle
- real estate
- online account

#### C. Auto-Generated Todo Lists
Turn findings into resource-linked todo lists and tasks.

Good fit with current todo design:

- list tied to resource
- tasks assigned to account members

#### D. Context Pack Pointers
Populate `ContextPackResponse.pointers` and `recents` with preparation-focused signals instead of only thin account facts.

That creates a clean future integration path for:

- conversation UIs
- advisor summaries
- daily readiness digests

### 4. AI Role in v1
Use AI selectively for explanation, ranking, and summarization.

#### Good v1 AI uses

- turn structured findings into plain-language explanations
- rank findings by urgency and family impact
- generate will plain-language summaries
- suggest concise next actions

#### Avoid in v1

- free-form open chat as the main product
- autonomous legal or financial advice
- hallucination-prone document interpretation without structured grounding

### 5. Data Strategy
Start with deterministic and graph-based detection.

Then layer in model-assisted capabilities:

#### Phase 1

- rule-based drift detection
- severity heuristics
- LLM-generated plain-language explanation

#### Phase 2

- learn which findings users resolve first
- learn which fixes improve readiness and sharing outcomes
- improve prioritization using anonymized product behavior data

#### Phase 3

- predict likely missing artifacts
- predict likely next actions by life stage
- recommend account setup patterns by household type

### 6. Positioning Risk
Avoid saying:

- "AI family assistant"
- "chat with your estate plan"
- "smart vault"

Those are weak and easy to imitate.

Prefer saying:

- "detect plan drift"
- "stay prepared as life changes"
- "turn family complexity into clear next steps"
- "continuity intelligence for families"

### 7. Recommended One-Sentence Direction
**Linden is building the family continuity intelligence layer that detects plan drift early and helps households stay prepared through life's hardest transitions.**

### 8. Recommended Next Step
Ship a narrow v1 around:

1. account-level readiness brief
2. 8-12 high-confidence drift detectors
3. plain-language findings
4. one-click todo generation
5. will summary generation

That is a real product wedge, not just an AI feature.
