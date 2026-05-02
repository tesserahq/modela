# Linden

Linden is an AI-powered life management platform designed to help individuals and families organize, protect, and plan their most important personal information in one secure place.

https://www.mylinden.family/

## What It Is

Linden goes beyond basic cloud storage by combining intelligent document organization, proactive insights, and human support. The goal is to reduce the cognitive and administrative burden of managing life logistics—especially across families, caregivers, and trusted advisors.

## Core Capabilities

- **AI-Driven Organization**  
  Automatically scans, categorizes, and structures documents such as legal, financial, medical, and personal records.

- **Contextual Insights & Reminders**  
  Identifies gaps, deadlines, and life events (e.g., expiring documents, estate updates, emergency readiness) and surfaces them proactively.

- **Estate & Legacy Planning**  
  Tools and workflows for wills, final wishes, and long-term planning, designed to be understandable and actionable for families.

- **Granular Sharing & Access Control**  
  Fine-grained permissions allow users to share specific information with family members, caregivers, lawyers, or financial advisors—without overexposure.

- **Concierge Support**  
  A hybrid model combining AI assistance with human help to guide users through organization, uploads, and planning.

## Security & Privacy

Linden is built with a privacy-first, zero-trust architecture. All sensitive data is encrypted, and AI interactions are reasoning-only and memoryless—data is analyzed on demand and not retained or used for training.

## Who It's For

Linden is designed for individuals and families who want a single, reliable source of truth for life planning, emergencies, and long-term continuity—without relying on ad hoc folders, spreadsheets, or institutional silos.

## Positioning

Linden is not a generic file vault or password manager. It is a comprehensive life hub focused on clarity, preparedness, and continuity across generations.

---

## How Linden Is Structured

Linden is built as a **single product API** (Linden API) that owns the domain data—wills, family members, documents, reminders, contacts, vehicles, real estate, insurance, and related life-planning entities. That API is the main backend that clients (web, mobile, MCP, etc.) talk to.

**Internal structure of the Linden API:**

- **Routers** — API surface is split into:
  - **Customer** — End-user endpoints (accounts, persons, wills, reminders, invitations, memberships, documents, etc.).
  - **Staff** — Internal/admin operations on the same domain data.
  - **Index** — Search-oriented endpoints that serve Indexa (or other consumers) with normalized payloads for indexing.

- **Services** — Business logic and persistence for each domain (wills, persons, contacts, reminders, etc.), using SQLAlchemy and the primary PostgreSQL database.

- **Commands** — Encapsulated operations (e.g. onboarding, creating invitations) that may coordinate multiple services and publish events (e.g. to NATS).

- **Middleware** — Authentication (via Tessera SDK and Identies), user onboarding, recently viewed tracking, and optional MCP auth.

Linden API integrates with external **Tessera** services (Custos, Vaulta, Identies, Sendly, etc.) over HTTP and, where applicable, publishes domain events over **NATS** so other systems (e.g. Indexa, Orcha) can react without being called directly.

---

## Tech Stack

Linden runs on a small set of core technologies:

| Technology | Role |
|------------|------|
| **PostgreSQL** | Primary relational store for all domain data. The Linden API uses SQLAlchemy (with asyncpg) and Alembic for schema and migrations. |
| **Redis** | Caching and ephemeral state: recently viewed items, session-like data, and (where used) LlamaIndex or other cache backends. Configured via `REDIS_HOST`, `REDIS_PORT`, `REDIS_NAMESPACE`. |
| **NATS** | Event bus for async, service-to-service communication. Domain events (e.g. invitation created) are published so subscribers (Indexa, Orcha, etc.) can index or run workflows without the API calling them directly. Configured via `NATS_URL`; can be disabled with `NATS_ENABLED=false`. |

The API is implemented in **Python** (FastAPI, Pydantic), and uses the **Tessera SDK** for auth, user resolution, and integration with Tessera services.

---

## Platform Services (Tessera Framework)

Linden is composed of a set of internal services (Tessera framework) that together power the platform:

### Linden API

The **core product backend**. It holds the user’s life-planning data: wills, family members (persons), contacts, vehicles, real estate, insurance, reminders, invitations, memberships, documents, and related entities. It uses the Tessera framework for auth, permissions, file storage, and events. Clients interact primarily with this API; Tessera services are used as supporting infrastructure.

### Tessera Framework

Tessera is a modular developer framework: a collection of Python-based services that provide identity, authorization, file storage, events, search, notifications, and more. Each service is independent and interoperable. Linden API consumes them over HTTP and/or NATS.

| Service | Role |
|--------|------|
| **Custos** | Authorization: permissions, roles, and access control (RBAC). Linden API uses Custos to enforce who can access which accounts and resources. |
| **Identies** | Identity and authentication: user identity, login, and auth flows. Linden API relies on Identies (via Tessera SDK) for JWT validation and user context. |
| **Vaulta** | File storage for documents and assets. Used for secure upload and retrieval of user files (e.g. attached to persons or accounts). |
| **Orcha** | Workflow automation: coordinates processes and life events across services (e.g. triggered by domain events from NATS). |
| **Eventa** | Event storage and timeline: records life events, milestones, and history for query and audit. |
| **Indexa** | Search indexing: consumes events from NATS, projects data into external search engines (e.g. Algolia, Typesense), and manages search index lifecycles and API keys for other services. |
| **Sendly** | Email sending: notifications, reminders, and system communications. |
| **Looply** | Contact and waitlist management: people, relationships, and onboarding flows. |
| **Conversa** | Conversational channels: unified interface to Telegram, WhatsApp, web chat, voice, etc., for connecting those platforms to internal systems. |

Together, **PostgreSQL**, **Redis**, and **NATS** form the data and messaging backbone; **Linden API** is the main application, and the **Tessera** services provide shared platform capabilities around it.
