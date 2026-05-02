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