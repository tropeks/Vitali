# Vitali — Architecture Document

> **Refs:** [PROJECT_BRIEF.md](./PROJECT_BRIEF.md) | [DATA_MODEL.md](./DATA_MODEL.md) |
> [SECURITY.md](./SECURITY.md) | [API_SPEC.md](./API_SPEC.md)

---

## 1. Architecture Pattern: Modular Monolith

### ADR-001: Modular Monolith over Microservices

**Status:** Accepted

**Context:** Solo developer building a complex healthcare SaaS. Need fast time-to-market,
low operational overhead, and ability to evolve into services later if needed.

**Decision:** Modular Monolith with clear domain boundaries (Django apps), backed by
schema-per-tenant PostgreSQL for data isolation.

**Alternatives considered:**
- *Microservices:* Rejected — operational overhead is prohibitive for solo dev. Network
  complexity, distributed debugging, container orchestration add months of work with zero
  user value.
- *Serverless:* Rejected — cold starts unacceptable for clinical workflows (doctors need
  instant response), vendor lock-in conflicts with VPS-first strategy.

**Consequences:**
- Single deployment unit = simpler CI/CD, debugging, and monitoring
- Django apps enforce module boundaries (emr, billing, pharmacy, ai, whatsapp)
- Each app can be extracted to a service later if scaling demands it
- Shared database with schema-per-tenant handles multi-tenancy

---

## 2. Tech Stack Decision Records

### ADR-002: Python + Django Backend

**Status:** Accepted

**Context:** Solo dev with no strong stack preference, building healthcare SaaS with AI features.

**Decision:** Python 3.12+ with Django 5.x + Django REST Framework

**Justification:**
- Django's "batteries included" philosophy saves months for solo dev: ORM, admin panel,
  auth system, form validation, migrations — all built-in
- Python is the lingua franca of AI/ML — seamless integration with LLM APIs, data
  processing (pandas), and future ML features
- `django-tenants` library provides production-tested schema-per-tenant multi-tenancy
- Django Admin gives instant back-office/admin panel for tenant management
- Massive ecosystem: Celery (async tasks), DRF (REST API), django-filter, drf-spectacular
  (OpenAPI docs)
- Healthcare precedent: OpenEMR community has Python tooling, HAPI FHIR has Python clients

**Alternatives considered:**
- *Node.js/Express:* Good for real-time but lacks Django's batteries-included approach.
  Solo dev would spend weeks building what Django gives for free. AI integration less native.
- *FastAPI:* Excellent async performance but missing Django's ORM maturity, admin panel,
  and ecosystem depth. Better as a microservice framework, not a full app framework.
- *.NET/C#:* Enterprise-grade but heavier ecosystem, smaller AI/ML library support,
  less open-source healthcare tooling.

**Consequences:**
- Synchronous by default (adequate for clinical workflows)
- Celery handles all async needs (AI calls, WhatsApp, TISS XML generation, reports)
- Django Admin = free back-office from day 1

---

### ADR-003: Next.js + React Frontend

**Status:** Accepted

**Context:** Need enterprise-grade UX comparable to Tasy, with professional components
and good developer experience for solo dev building complex clinical interfaces.

**Decision:** Next.js 14+ (App Router) + React 18+ + Tailwind CSS + shadcn/ui

**Justification:**
- React has the largest component ecosystem — critical for building complex clinical UIs
  (data tables, forms, charts, calendars) without building from scratch
- shadcn/ui provides production-grade, accessible components with professional aesthetics
  (matches Tasy-level quality expectation)
- Next.js App Router gives file-based routing, server components for performance, and
  API routes for BFF (Backend for Frontend) pattern
- Tailwind CSS enables rapid UI development with consistent design system
- AI-assisted development works best with React (largest training data in LLMs)

**Alternatives considered:**
- *Vue/Nuxt:* Excellent DX but smaller component ecosystem for complex healthcare UIs
- *HTMX + Django Templates:* Simpler stack but inadequate for the rich interactive
  interfaces needed (prescription builder, patient timeline, real-time dashboards)
- *Angular:* Over-engineered for solo dev, steeper learning curve

**Consequences:**
- Two codebases (Django API + Next.js frontend) — more complexity but necessary for UX goals
- BFF pattern via Next.js API routes simplifies frontend data fetching
- SSR for initial load performance; SPA behavior after hydration

---

### ADR-004: PostgreSQL with Schema-per-Tenant

**Status:** Accepted

**Context:** SaaS multi-tenant handling sensitive health data (LGPD). Need strong data
isolation, complex relational queries, and proven healthcare data patterns.

**Decision:** PostgreSQL 16+ with django-tenants (schema-per-tenant isolation)

**Justification:**
- Schema-per-tenant provides true data isolation — critical for LGPD compliance with
  health data (dados sensíveis). Each tenant's data is in a separate PostgreSQL schema,
  making it impossible for query bugs to leak data across tenants.
- PostgreSQL's JSONB handles semi-structured clinical data (evolução, anamnese) without
  sacrificing relational integrity for structured data (patients, prescriptions, billing)
- Full-text search built-in (pg_trgm + tsvector) — no need for Elasticsearch initially
- pgvector extension available for future AI embeddings (semantic search on clinical notes)
- Row-level security as additional defense layer
- Proven in healthcare: HAPI FHIR server, OpenMRS, multiple production EMR systems

**Alternatives considered:**
- *Shared schema with tenant_id:* Simpler but data leak risk is unacceptable for health data
- *Database-per-tenant:* Maximum isolation but operational nightmare (migrations, connections)
- *MongoDB:* Poor fit for relational healthcare data (patients→encounters→prescriptions→items)

**Consequences:**
- django-tenants handles schema creation, routing, and migrations automatically
- Shared `public` schema for: tenant registry, billing, feature flags, platform admin
- Tenant schemas contain: all clinical, operational, and financial data
- Migration complexity: must run migrations per-schema (django-tenants handles this)
- Connection pooling via PgBouncer required as tenant count grows

---

### ADR-005: Redis for Cache + Queue

**Status:** Accepted

**Decision:** Redis 7+ for session cache, Celery broker, rate limiting, and real-time features.

**Justification:** Single service that handles caching, message brokering (Celery), rate
limiting, and pub/sub for future real-time features. Operationally simple for solo dev.

**Alternative:** RabbitMQ for queuing — rejected because Redis handles both cache and queue,
reducing infrastructure footprint.

---

### ADR-006: Evolution API for WhatsApp Integration

**Status:** Accepted

**Context:** Need WhatsApp integration for patient engagement. Official WhatsApp Business
API requires BSP (Business Solution Provider) with monthly costs.

**Decision:** Evolution API (open-source, self-hosted) for MVP, with migration path to
official WhatsApp Business API via BSP (360dialog/Gupshup) when scaling.

**Justification:**
- Free and self-hosted — fits budget constraint
- REST API for sending/receiving messages, webhooks for incoming
- Docker deployment, integrates naturally with our stack
- Active Brazilian community (well-documented in PT-BR)

**Consequences:**
- Risk: Evolution API operates in gray area of WhatsApp ToS — acceptable for MVP/pilot
  but must migrate to official API for production at scale
- Abstraction layer in code: `WhatsAppGateway` interface that can swap implementations
- Official API migration: just swap the gateway implementation, no business logic changes

---

### ADR-007: LLM API for AI Features

**Status:** Accepted

**Decision:** Anthropic Claude API as primary LLM, OpenAI as fallback. All AI processing
via API calls, no local model training.

**Justification:**
- Solo dev cannot maintain ML infrastructure
- API-based = pay-per-use, scales with tenant usage
- Claude excels at structured medical text analysis (TUSS coding, clinical documentation)
- Fallback provider prevents single-vendor dependency

**Cost model:**
- TUSS auto-coding: ~$0.002-0.005 per suggestion (short prompt + structured output)
- WhatsApp chatbot: ~$0.001-0.003 per interaction
- At 100 interactions/day across all tenants: ~$15-30/month — absorbable in pricing

---

### ADR-008: Apache Superset for BI (Phase 2)

**Status:** Proposed (Phase 2)

**Decision:** Apache Superset embedded dashboards with row-level security per tenant.

**Justification:** Production-grade BI tool, embeddable via iframe with auth tokens,
supports PostgreSQL natively, pre-built chart types cover all healthcare KPIs.
Alternative (Metabase) is simpler but less flexible for embedding.

---

## 3. High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENTS                                   │
│  [Browser/SPA] ──HTTPS──→ [Next.js Frontend]                   │
│  [WhatsApp]    ──webhook─→ [Evolution API]                      │
│  [Mobile PWA]  ──HTTPS──→ [Next.js Frontend]                   │
└────────────────────┬──────────────────┬─────────────────────────┘
                     │                  │
                     ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GATEWAY LAYER                                 │
│  [Nginx Reverse Proxy + SSL + Rate Limiting]                    │
│  ├── /app/*        → Next.js (port 3000)                        │
│  ├── /api/*        → Django DRF (port 8000)                     │
│  ├── /ws/*         → Django Channels (WebSocket)                │
│  ├── /whatsapp/*   → Evolution API (port 8080)                  │
│  └── /superset/*   → Apache Superset (port 8088) [Phase 2]     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              APPLICATION LAYER (Django Modular Monolith)          │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  core    │ │   emr    │ │ billing  │ │ pharmacy │           │
│  │ ─────── │ │ ─────── │ │ ─────── │ │ ─────── │           │
│  │ Tenants  │ │ Patient  │ │ TISS/XML │ │ Stock    │           │
│  │ Users    │ │ Records  │ │ Guides   │ │ Dispense │           │
│  │ Auth     │ │ Prescr.  │ │ Glosas   │ │ Purchase │           │
│  │ Feature  │ │ Evolução │ │ TUSS DB  │ │ Lots     │           │
│  │ Flags    │ │ Schedule │ │ Reports  │ │ Controlled│          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────────┐            │
│  │    ai    │ │ whatsapp │ │      analytics       │            │
│  │ ─────── │ │ ─────── │ │ ──────────────────── │            │
│  │ TUSS    │ │ Chatbot  │ │ Billing KPIs         │            │
│  │ Coding   │ │ Schedule │ │ Denial by Insurer    │            │
│  │ LLM Gate │ │ Reminder │ │ Glosa AI Accuracy    │            │
│  │ Prompts  │ │ Gateway  │ │ Revenue Trend        │            │
│  └──────────┘ └──────────┘ └──────────────────────┘            │
│                                                                   │
│  [Celery Workers] ←──REDIS──→ [Celery Beat (Scheduler)]        │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATA LAYER                                    │
│                                                                   │
│  ┌──────────────────────┐  ┌──────────┐  ┌──────────┐          │
│  │   PostgreSQL 16      │  │  Redis 7 │  │  S3/     │          │
│  │   ┌───────────────┐  │  │  ──────  │  │  MinIO   │          │
│  │   │ public schema │  │  │  Cache   │  │  ──────  │          │
│  │   │ ─ tenants     │  │  │  Queue   │  │  Files   │          │
│  │   │ ─ billing     │  │  │  Session │  │  Docs    │          │
│  │   │ ─ features    │  │  │  PubSub  │  │  Backups │          │
│  │   ├───────────────┤  │  └──────────┘  └──────────┘          │
│  │   │ tenant_001    │  │                                       │
│  │   │ ─ patients    │  │  ┌──────────────────────┐            │
│  │   │ ─ encounters  │  │  │  External APIs       │            │
│  │   │ ─ billing     │  │  │  ─ Claude API (AI)   │            │
│  │   ├───────────────┤  │  │  ─ WhatsApp Bus. API │            │
│  │   │ tenant_002    │  │  │  ─ ANS/TISS gateway  │            │
│  │   │ ─ patients    │  │  │  ─ SMTP (email)      │            │
│  │   │ ─ ...         │  │  └──────────────────────┘            │
│  │   └───────────────┘  │                                       │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
[Browser] --(HTTPS/REST)--> [Nginx]
[Nginx] --(proxy)--> [Next.js Frontend]
[Next.js] --(REST API)--> [Django DRF API]
[Django API] --(ORM)--> [PostgreSQL (tenant schema)]
[Django API] --(dispatch)--> [Celery via Redis]
[Celery Worker] --(HTTPS)--> [Claude API] (AI features)
[Celery Worker] --(REST)--> [Evolution API] (WhatsApp)
[Celery Worker] --(XML/HTTPS)--> [ANS TISS endpoint]
[Celery Worker] --(S3 API)--> [MinIO/S3] (file storage)
[Evolution API] --(webhook)--> [Django API] (incoming messages)
[Celery Beat] --(scheduled)--> [Celery Worker] (reminders, reports)
```

---

## 4. Component Specification

### 4.1 Core Module (`apps/core/`)

**Responsibility:** Multi-tenancy, authentication, authorization, feature flags, billing.

**Inputs:** User credentials, tenant configuration, subscription data
**Outputs:** JWT tokens, tenant context, feature availability

**Key Models:** Tenant, User, Role, Permission, FeatureFlag, Subscription, Plan, PlanModule

**Dependencies:** PostgreSQL (public schema), Redis (sessions)

**Scaling:** Stateless — scale horizontally by adding Django instances behind Nginx.

**Failure mode:** If core is down, entire system is down. Mitigated by health checks and
auto-restart in Docker. Redis failure degrades to DB-backed sessions.

**Feature Flag System:**
```python
# Usage in any view/serializer
if tenant_has_feature(request.tenant, 'module_pharmacy'):
    # show pharmacy endpoints
if tenant_has_feature(request.tenant, 'ai_tuss_coding'):
    # enable AI-assisted TUSS suggestions
```

---

### 4.2 EMR Module (`apps/emr/`)

**Responsibility:** Patient records, clinical documentation, scheduling, prescriptions.

**Inputs:** Patient data, clinical observations, prescription orders, schedule requests
**Outputs:** Structured medical records, prescription documents, appointment confirmations

**Key Models:** Patient, Encounter, ClinicalNote, Prescription, PrescriptionItem,
MedicalHistory, Allergy, Vital, Appointment, Schedule, Professional

**Dependencies:** Core (auth/tenancy), Pharmacy (drug catalog), AI (TUSS coding)

**Scaling:** Read-heavy — PostgreSQL read replicas if needed.

**Failure mode:** Read failures show cached data. Write failures queue to Celery for retry.
Critical writes (prescriptions) are synchronous with immediate feedback.

---

### 4.3 Billing Module (`apps/billing/`)

**Responsibility:** TISS/TUSS compliance, guide generation, XML export, glosa management.

**Inputs:** Encounter data, procedures performed, materials used, TUSS codes
**Outputs:** TISS XML files (guias), billing reports, glosa tracking

**Key Models:** TISSGuide, TISSBatch, TUSSCode, BillingItem, Glosa, GlosaAppeal,
InsuranceProvider, Contract, PriceTable

**Dependencies:** Core (tenancy), EMR (encounters/procedures), AI (TUSS auto-coding)

**Key Feature — TUSS Code Database:**
- Import official ANS TUSS table (CSV → PostgreSQL)
- Full-text search on procedure descriptions
- AI-enhanced: LLM suggests top 3 TUSS codes from free-text procedure description
- Version tracking (ANS updates the table periodically)

**Scaling:** Batch XML generation offloaded to Celery workers.

**Failure mode:** XML generation failures logged and retryable. Glosa tracking is non-critical path.

---

### 4.4 Pharmacy Module (`apps/pharmacy/`)

**Responsibility:** Medication/material inventory, dispensation, purchase orders, controlled drugs.

**Inputs:** Stock entries, dispensation orders, purchase requests
**Outputs:** Current stock levels, dispensation records, purchase orders, expiry alerts

**Key Models:** Drug, Material, StockItem, StockMovement, Dispensation, PurchaseOrder,
PurchaseOrderItem, Supplier, Lot, ExpiryAlert

**Dependencies:** Core (tenancy), EMR (prescriptions trigger dispensation)

**Scaling:** Low-traffic module — single instance sufficient.

**Failure mode:** Stock count discrepancies handled by reconciliation feature.
Dispensation without system = manual override with post-entry (contingency mode).

---

### 4.5 AI Module (`apps/ai/`)

**Responsibility:** LLM integration layer, prompt management, AI feature orchestration.

**Inputs:** Clinical text, procedure descriptions, conversation context
**Outputs:** TUSS code suggestions, structured clinical data, chatbot responses

**Key Components:**
- `LLMGateway` — Abstract interface for LLM providers (Claude, OpenAI)
- `PromptRegistry` — Versioned prompt templates for each AI feature
- `TUSSCoder` — TUSS auto-coding pipeline (text → LLM → top-3 suggestions with confidence)
- `ChatEngine` — WhatsApp conversation state machine

**Dependencies:** Core (tenancy, feature flags), external LLM APIs

**Scaling:** All AI calls are async via Celery. Rate limiting per tenant prevents cost spikes.

**Failure mode:** AI failures are graceful — system works without AI, user just doesn't get
suggestions. Fallback: traditional text search on TUSS database.

**Cost Control:**
- Token budget per tenant per month (configurable in subscription)
- Caching of repeated TUSS queries (same procedure text → same suggestion)
- Short prompts with structured output (minimize token usage)

---

### 4.6 WhatsApp Module (`apps/whatsapp/`)

**Responsibility:** Patient communication via WhatsApp — scheduling, reminders, confirmations.

**Inputs:** Incoming WhatsApp messages (webhooks), scheduled reminder triggers
**Outputs:** Outgoing messages, appointment bookings, confirmation status

**Key Components:**
- `WhatsAppGateway` — Interface abstracting Evolution API / official API
- `ConversationFSM` — 13-state finite state machine for chatbot conversations (opt-in → scheduling → confirmation)
- `ReminderEngine` — Celery Beat tasks for appointment reminders
- `MessageTemplate` — Pre-approved message templates (required by WhatsApp Business API)

**Dependencies:** Core (tenancy), EMR (appointments), AI (chatbot intelligence)

**Flow:**
```
Patient sends "Agendar consulta" via WhatsApp
  → Evolution API webhook → Django endpoint
  → ConversationFlow identifies intent
  → AI module processes natural language (optional, can be rule-based)
  → EMR module checks available slots
  → Response sent back via WhatsApp Gateway
  → Appointment created in EMR
  → Reminder scheduled in Celery Beat (24h before, 2h before)
```

**Failure mode:** WhatsApp gateway down = appointments via phone/web still work.
Messages queued in Redis for retry when gateway recovers.

---

## 5. Infrastructure Blueprint

### 5.1 VPS Phase (MVP)

```
Single VPS (Hetzner/Contabo) — 8 vCPU, 16GB RAM, 200GB NVMe
├── Docker Compose
│   ├── nginx (reverse proxy + SSL via Let's Encrypt)
│   ├── django (gunicorn, 4 workers)
│   ├── nextjs (Node.js, production build)
│   ├── celery-worker (2 workers)
│   ├── celery-beat (scheduler)
│   ├── postgres (16, with daily pg_dump backups)
│   ├── redis (7, persistence enabled)
│   ├── evolution-api (WhatsApp gateway)
│   └── minio (S3-compatible object storage)
├── Automated backups → external storage (Backblaze B2/Wasabi)
└── Monitoring: Uptime Kuma + Grafana + Prometheus
```

**Estimated cost:** ~R$200-400/mês (Hetzner CX41 or equivalent)

### 5.2 AWS Migration Phase (Scale)

```
AWS Account
├── ECS Fargate (containerized services)
│   ├── django service (auto-scaling 2-10 tasks)
│   ├── nextjs service (auto-scaling 2-10 tasks)
│   ├── celery-worker service (auto-scaling based on queue depth)
│   └── celery-beat service (1 task)
├── RDS PostgreSQL (Multi-AZ, automated backups)
├── ElastiCache Redis (cluster mode)
├── S3 (file storage, replacing MinIO)
├── ALB (Application Load Balancer + WAF)
├── CloudFront (CDN for static assets)
├── Route 53 (DNS)
├── ACM (SSL certificates)
├── CloudWatch (monitoring + alerting)
└── Secrets Manager (credentials rotation)
```

### 5.3 CI/CD Pipeline

```
GitHub Repository (monorepo)
  ├── /backend (Django)
  ├── /frontend (Next.js)
  ├── /infra (Docker Compose + Terraform)
  └── /docs (architecture docs)

GitHub Actions Pipeline:
  1. PR → lint + type check + unit tests
  2. Merge to main → build Docker images + integration tests
  3. Tag release → push images to registry + deploy to staging
  4. Manual approval → deploy to production
  5. Post-deploy → smoke tests + health checks
```

---

## 6. Key Technical Decisions Summary

| Decision | Choice | Key Reason |
|----------|--------|------------|
| Architecture | Modular Monolith | Solo dev, low ops overhead |
| Backend | Django 5 + DRF | Batteries included, Python AI ecosystem |
| Frontend | Next.js + shadcn/ui | Enterprise UX, largest React ecosystem |
| Database | PostgreSQL 16 | JSONB + schema-per-tenant + pgvector |
| Multi-tenancy | Schema-per-tenant | LGPD data isolation requirement |
| Cache/Queue | Redis 7 | Single service for cache + Celery broker |
| Async | Celery + Celery Beat | AI calls, WhatsApp, XML gen, reminders |
| WhatsApp | Evolution API → Official | Free MVP, migration path built-in |
| AI Engine | Claude API (+ OpenAI fallback) | Best structured output, pay-per-use |
| BI (Phase 2) | Apache Superset | Embeddable, PostgreSQL native |
| PACS (Phase 2) | Orthanc + OHIF Viewer | Industry standard open-source |
| Object Storage | MinIO → S3 | S3-compatible, zero migration effort |
| Containerization | Docker Compose → ECS | Portable, VPS to AWS without rewrite |
| Monitoring | Grafana + Prometheus | Industry standard, free |

---

*Next: [DATA_MODEL.md](./DATA_MODEL.md) | [SECURITY.md](./SECURITY.md)*
