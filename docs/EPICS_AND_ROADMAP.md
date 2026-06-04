# Vitali — Epics, Stories & Roadmap

> **Refs:** [VISION-AI-NATIVE.md](./VISION-AI-NATIVE.md) | [PROJECT_BRIEF.md](./PROJECT_BRIEF.md) |
> [ARCHITECTURE.md](./ARCHITECTURE.md) | [DATA_MODEL.md](./DATA_MODEL.md)

---

## AI-Native Reframe (2026-06)

> Esta seção é **aditiva**. Nada abaixo dela foi removido — o registro histórico,
> os épicos e os status de "shipped" permanecem intactos. Ela apenas reorienta a
> **prioridade** do roadmap em torno da tese AI-native aprovada em office-hours.

**A tese (ver [VISION-AI-NATIVE.md](./VISION-AI-NATIVE.md)):** o Vitali deixa de ser
um sistema de *registro* (CRUD que anota o que aconteceu, como Tasy/MV/TOTVS) e passa
a ser uma **inteligência ativa que intercepta o erro antes que ele alcance o paciente.**
O fosso não é contagem de módulos nem velocidade — é **arquitetural** (loop fechado na
espinha do workflow) e **composto** (um data flywheel de alertas + overrides + desfechos
que nenhum incumbente de núcleo legado consegue igualar, e que ninguém aluga da
OpenAI/Anthropic). O padrão que se repete em todo módulo: **Observe → Preveja →
Intercepte → Aprenda.**

### Entregue neste ciclo (SHIPPED — flag-gated OFF) — 2026-06

> **Built ≠ live.** As **três cunhas AI-native** foram construídas e mergeadas no
> master. Todas **OFF por padrão** (cada uma atrás de um `FeatureFlag` per-tenant) e
> nenhuma processa nada até que **dados validados por humano** sejam fornecidos.
> **Nada de número clínico/contratual/ANS foi inventado em código.** Índice
> consolidado: [`AI-NATIVE-WEDGES.md`](./AI-NATIVE-WEDGES.md).

| Wedge | Flag (default OFF) | Estado | Para ir ao ar (gate humano) |
|-------|--------------------|--------|------------------------------|
| **Dose-safety** | `dose_safety` | Motor `DoseChecker` (`apps/pharmacy/services/dose_checker.py`) + dose-engine v2 (frequency band / `dose_role` / enforcement-advise) + soft-stop em `Prescription.sign` e `DispenseView` + `AISafetyAlert(source)` + `DoseSafetyModal`. **SHIPPED.** | **Flag ON** + **formulário validado por farmacêutico** (`MedicationFormulary`/`DoseRule`) — decisão **D-T1, PENDENTE**. Tabelas de produção ficam VAZIAS até a assinatura. Ver [`plans/DOSE-SAFETY-WEDGE.md`](./plans/DOSE-SAFETY-WEDGE.md) e [`formulary-package/`](./formulary-package/). |
| **Glosa-interception** | `glosa_safety` | Motor `GlosaChecker` (`apps/billing/services/glosa_checker.py`) + soft-stop por-guia em `TISSBatchViewSet.close` + `GlosaSafetyAlert` + `Authorization` + backfill item-level + compat clínica (`TUSSCode` idade/sexo/CID) + teto por procedimento + `GlosaSafetyModal`. **SHIPPED.** | **Flag ON.** Checks de maior valor rodam **sem dado novo**; os checks clínicos/teto/autorização ficam inertes (advise) até **import ANS / config do estabelecimento** — verdade externa, nunca inventada. Ver [`plans/GLOSA-WEDGE.md`](./plans/GLOSA-WEDGE.md). |
| **Stockout-prediction** | `stockout_safety` | `StockoutChecker` (SMA de velocidade) + `StockAlert` + validade FEFO (`expiry_waste`) + `StockRiskView` + painel de risco + job noturno de flywheel (grading). **SHIPPED.** | **Flag ON** + acúmulo de histórico de consumo. Velocidade é **derivada** de `StockMovement` (não inventada); `lead_time_days`/`safety_stock`/`reorder_point` são config per-establishment, **inertes** até preenchidos. **Advise-only — nunca bloqueia dispensa.** Ver [`plans/STOCKOUT-WEDGE.md`](./plans/STOCKOUT-WEDGE.md). |

Padrão compartilhado (os 4 princípios da §5 da [Visão](./VISION-AI-NATIVE.md), em código):
motor determinístico puro (autoritativo) + orquestrador + alerta persistente +
flag per-tenant (default OFF) + flywheel via `AuditLog`. O LLM, quando presente, só
**explica** — nunca decide o portão. Postura **advise-vs-block** por wedge. Isto
**prova o padrão de loop fechado** (item 2 abaixo) para glosa e estoque — mas as
três permanecem **construídas, não no ar**, até flag + dado humano.

### Prioridade reorientada

**1. Flagship — Cunha de segurança de dose (dose-safety interception).**
A bandeira do produto. O sistema conhece a dose correta para o paciente (peso / idade /
função renal) e intercepta o desvio nos **três portões** da jornada do medicamento —
prescrição → farmácia → administração à beira-leito — começando por **injetáveis**
(maior risco, maior letalidade). Evolui o `AISafetyAlert` (Sprint 15 / S-063) e a
cascata existente **E-013 / F-03** (encounter-signed) + **F-12** (AI safety alert):
hoje uma checagem de LLM commodity, a ser aprofundada na espinha real de interceptação
de dose em tempo real, que aprende com cada override.
*Observe* a prescrição → *preveja* a faixa segura para aquele paciente → *intercepte*
o desvio nos três gates → *aprenda* com cada override e desfecho.

**2. Replicar o padrão de loop fechado aos demais loops de alto valor.**
O **mesmo motor** observe-preveja-intercepte-aprenda, aplicado às próximas dores:

| Loop | Observe → Preveja → Intercepte → Aprenda | Evolui de | Estado |
|------|-------------------------------------------|-----------|--------|
| **Glosa-prevention** | Observa a guia em montagem → prevê o risco/motivo de glosa → intercepta antes do envio do lote → aprende com cada glosa/recurso real | E-006 S-024, E-008, Glosa AI (Sprint 10) | **SHIPPED** (motor determinístico `glosa_safety`, flag OFF — ver "Entregue neste ciclo") |
| **Inventory-rupture** | Observa o ledger de estoque → prevê a ruptura antes do `min_stock` → intercepta (alerta proativo + reposição sugerida) → aprende com o consumo real | E-007 S-027, F-06, `apps.pharmacy_ai` | **SHIPPED** (motor determinístico `stockout_safety`, flag OFF, advise-only — ver "Entregue neste ciclo") |
| **No-show** | Observa o padrão do paciente → prevê o risco de falta → intercepta com re-engajamento + reabertura de vaga → aprende com o comparecimento real | E-005, E-009 S-034, F-11 | Planejado |

### Reprioritization — moat vs. table-stakes

- **Moat work (loop-fechado / inteligência):** é onde o esforço de excelência mora.
  A cunha de dose e os três loops acima recebem profundidade obsessiva. É o que torna
  o produto mais defensável **com o uso**.
- **Table-stakes (compliance / higiene / paridade de CRUD):** EMR, faturamento TISS,
  cadastro, RBAC, LGPD, etc. são **cleared para a barra de piloto — não gold-plated.**
  Precisam funcionar, ser compliant e não atrapalhar; não precisam ser melhores que o
  Tasy. Bom o suficiente para o piloto é o teto, não o chão.
- **SHELVED até um loop fechado justificar (itens "primitive-only" da Phase 3):**
  os primitivos que hoje são só esqueleto sem loop estão **explicitamente engavetados**
  até que uma interceptação de loop fechado os puxe:
  - **Telemedicina** — state machine de sessão (`apps.telemedicine`), sem WebRTC/loop.
  - **Mobile** — `MobileDevice`/`PushDelivery` (`apps.mobile`), tabela sem app nem loop.
  - **"AI" baseada em regra** — `smart_scheduling` e `pharmacy_ai` no estado *rule-based*
    determinístico atual contam como primitivo; só viram prioridade quando promovidos a
    loop fechado real (observe→preveja→intercepte→**aprenda** com modelo treinado).

### O que isto DE-prioriza (honestidade)

- Acabamento de UI/feature de paridade com incumbentes além da barra de piloto.
- Expansão de superfície de módulos ("mais um módulo") sem um loop fechado por trás.
- Phase-3 primitive-only: telemedicina (WebRTC), mobile (app React Native),
  smart-scheduling e pharmacy-ai **enquanto rule-based** — todos engavetados até justificados.
- Multi-country / i18n completo, FHIR além da cobertura atual, Superset embedding —
  permanecem table-stakes/oportunísticos, não moat.

---

## 1. Epic Overview

| Epic | Name | Priority | Deps | Complexity |
|------|------|----------|------|------------|
| E-001 | Foundation & Infrastructure | P0 | None | L |
| E-002 | Auth & Multi-Tenancy | P0 | E-001 | L |
| E-003 | Core — Patient Management | P0 | E-002 | M |
| E-004 | EMR — Clinical Records | P0 | E-003 | XL |
| E-005 | Scheduling & Appointments | P0 | E-003 | M |
| E-006 | Billing — TISS/TUSS | P0 | E-004 | XL |
| E-007 | Pharmacy & Inventory | P0 | E-003, E-004 | L |
| E-008 | AI — TUSS Auto-Coding | P0 | E-006 | M |
| E-009 | WhatsApp — Patient Engagement | P0 | E-005 | L |
| E-010 | Subscription & Feature Flags | P1 | E-002 | M |
| E-011 | BI & Analytics | P1 | E-004, E-006 | L |
| E-012 | DICOM/PACS Integration | P2 | E-004 | L |
| E-013 | Workflow Intelligence (Sistema Inteligente) | P1 | E-002, E-005 | XL |

---

## 2. Epic Details

### E-001: Foundation & Infrastructure
**Goal:** Monorepo setup, Docker environment, CI/CD pipeline, base project structure.
**Dependencies:** None (foundational)

**Stories:**
```
[S-001] Setup monorepo structure (backend/ frontend/ infra/ docs/)
  Tasks:
    - [ ] Initialize Django project with poetry
    - [ ] Initialize Next.js project with TypeScript
    - [ ] Create docker-compose.yml (django, nextjs, postgres, redis, nginx)
    - [ ] Configure Nginx reverse proxy with SSL (self-signed for dev)
    - [ ] Create .env.example with all required variables
    - [ ] Setup Makefile with common commands (up, down, migrate, shell, test)
  Story Points: 5

[S-002] CI/CD Pipeline
  Tasks:
    - [ ] GitHub Actions: lint (ruff + eslint) on PR
    - [ ] GitHub Actions: test (pytest + jest) on PR
    - [ ] GitHub Actions: build Docker images on merge to main
    - [ ] GitHub Actions: deploy to staging on tag
    - [ ] Dockerfile for Django (multi-stage, production-ready)
    - [ ] Dockerfile for Next.js (multi-stage, standalone output)
  Story Points: 5

[S-003] Monitoring & Logging Setup
  Tasks:
    - [ ] Add Prometheus metrics endpoint to Django
    - [ ] Configure Grafana with basic dashboards (request rate, errors, latency)
    - [ ] Setup structured logging (JSON format) with django-structlog
    - [ ] PII redaction middleware for logs
    - [ ] Uptime Kuma for health check monitoring
  Story Points: 3

[S-004] Database Foundation
  Tasks:
    - [ ] Install and configure django-tenants
    - [ ] Create Tenant and Domain models in public schema
    - [ ] Create management command: create_tenant
    - [ ] Configure PostgreSQL with connection pooling (PgBouncer)
    - [ ] Automated backup script (pg_dump → encrypted → Backblaze B2)
    - [ ] Restore test script
  Story Points: 5
```

---

### E-002: Auth & Multi-Tenancy
**Goal:** Users can register tenants, login, and operate within their isolated tenant.
**Dependencies:** E-001

**Stories:**
```
[S-005] Tenant Registration Flow
  Acceptance Criteria:
    - Admin creates tenant via API (name, slug, CNPJ)
    - PostgreSQL schema created automatically
    - Default admin user created for tenant
    - Default roles created (admin, medico, enfermeiro, recepcionista, farmaceutico, faturista)
  Tasks:
    - [ ] Tenant creation API endpoint
    - [ ] Schema provisioning via django-tenants signals
    - [ ] Default role seeding per tenant
    - [ ] Tenant admin user creation
  Story Points: 5

[S-006] Authentication System
  Acceptance Criteria:
    - Users login with email + password
    - JWT access token (15min) + refresh token (7d) issued
    - Refresh token rotation enabled
    - Account lockout after 5 failed attempts
    - Password complexity validation (12+ chars, mixed)
  Tasks:
    - [ ] Configure djangorestframework-simplejwt
    - [ ] Login endpoint with rate limiting (5/min/IP)
    - [ ] Refresh endpoint with token rotation
    - [ ] Logout endpoint (blacklist refresh token)
    - [ ] Password change endpoint
    - [ ] Account lockout middleware
    - [ ] Tests: login, logout, refresh, lockout, password change
  Story Points: 8

[S-007] RBAC Authorization
  Acceptance Criteria:
    - Each API endpoint requires specific permission
    - Roles have configurable permission sets
    - Tenant admin can create custom roles
    - Permission check happens at API layer
  Tasks:
    - [ ] Role and Permission models
    - [ ] DRF permission classes per module
    - [ ] Role CRUD API (admin only)
    - [ ] User-role assignment API
    - [ ] Permission matrix documentation
  Story Points: 5

[S-008] Audit Logging
  Acceptance Criteria:
    - All auth events logged (login, logout, failed)
    - All data changes logged (create, update, delete) with before/after
    - Logs are append-only (no modification)
    - Admin can view audit log via API
  Tasks:
    - [ ] AuditLog model (append-only, partitioned by month)
    - [ ] Django signal-based automatic audit logging
    - [ ] Audit log API endpoint (admin, read-only)
    - [ ] PII redaction in audit log API responses
  Story Points: 5

[S-009] Frontend Auth & Layout
  Acceptance Criteria:
    - Login page with professional design (Tasy-inspired)
    - Authenticated layout with sidebar navigation
    - Role-based menu items (only show modules user has access to)
    - Responsive design (works on tablet for bedside use)
  Tasks:
    - [ ] Next.js auth middleware (JWT cookie-based)
    - [ ] Login page component
    - [ ] Authenticated layout with sidebar
    - [ ] Role-based navigation rendering
    - [ ] User profile/settings page
    - [ ] shadcn/ui theme configuration (professional, healthcare palette)
  Story Points: 8
```

---

### E-003: Core — Patient Management
**Goal:** Complete patient registration, search, and management.
**Dependencies:** E-002

**Stories:**
```
[S-010] Patient CRUD
  Acceptance Criteria:
    - Register patient with full demographic data
    - CPF validation (format + algorithm)
    - CPF encrypted at rest
    - Medical record number auto-generated
    - Patient photo upload
    - Search by name (fuzzy), CPF, medical record number, WhatsApp
  Tasks:
    - [ ] Patient model with encrypted fields
    - [ ] Patient serializer with CPF validation
    - [ ] CRUD API endpoints
    - [ ] Full-text search with pg_trgm
    - [ ] Photo upload to MinIO/S3
    - [ ] Frontend: patient registration form
    - [ ] Frontend: patient search/list with filters
    - [ ] Frontend: patient detail/profile page
  Story Points: 8

[S-011] Insurance Data Management
  Acceptance Criteria:
    - Patient can have multiple insurance plans
    - Insurance provider registry (name, ANS code, CNPJ)
    - Card number, plan name, validity tracked
  Tasks:
    - [ ] InsuranceProvider model and CRUD
    - [ ] Patient insurance data (JSONB field + management UI)
    - [ ] Insurance validation (card format per provider)
  Story Points: 3

[S-012] Allergy & Medical History
  Acceptance Criteria:
    - Record allergies with substance, reaction, severity
    - Record medical history (personal, family, surgical)
    - Allergy alerts visible on patient header (always-on banner)
  Tasks:
    - [ ] Allergy model and CRUD API
    - [ ] MedicalHistory model and CRUD API
    - [ ] Frontend: allergy alert component (red banner on patient pages)
    - [ ] Frontend: medical history timeline view
  Story Points: 5
```

---

### E-004: EMR — Clinical Records
**Goal:** Full electronic medical records with encounters, notes, and prescriptions.
**Dependencies:** E-003

**Stories:**
```
[S-013] Encounter Management
  Acceptance Criteria:
    - Create encounter (outpatient, inpatient, emergency)
    - Record chief complaint, vitals, diagnosis (CID-10)
    - Encounter lifecycle (open → in_progress → completed)
    - CID-10 database with search
  Tasks:
    - [ ] Encounter model and API
    - [ ] CID-10 database import (WHO CSV)
    - [ ] CID-10 search endpoint (code + description fuzzy)
    - [ ] Frontend: encounter creation flow
    - [ ] Frontend: encounter detail with tabs (notes, prescriptions, procedures)
    - [ ] Frontend: vitals input form
  Story Points: 8

[S-014] Clinical Notes (Evolution)
  Acceptance Criteria:
    - Create clinical notes linked to encounter
    - Support SOAP format (Subjetivo, Objetivo, Avaliação, Plano)
    - Note signing (becomes immutable after signing)
    - Amendments create new notes referencing original
  Tasks:
    - [ ] ClinicalNote model and API
    - [ ] SOAP structured input
    - [ ] Digital signing flow (hash content on sign)
    - [ ] Immutability enforcement (reject updates on signed notes)
    - [ ] Frontend: rich text note editor
    - [ ] Frontend: note signing UI with confirmation
  Story Points: 8

[S-015] Prescription Builder
  Acceptance Criteria:
    - Create medication prescriptions with items
    - Drug catalog search (fuzzy search on name/generic)
    - Dosage, route, frequency, duration fields
    - Prescription signing (required before dispensation)
    - Print-ready prescription format
  Tasks:
    - [ ] Prescription and PrescriptionItem models
    - [ ] Drug search endpoint (from pharmacy module catalog)
    - [ ] Prescription builder API
    - [ ] Prescription signing flow
    - [ ] Frontend: prescription builder UI (add items, search drugs, set dosage)
    - [ ] Frontend: prescription print view (PDF generation)
  Story Points: 13

[S-016] Patient Timeline
  Acceptance Criteria:
    - Unified chronological view of all patient events
    - Encounters, prescriptions, dispensations, lab results (future)
    - Filterable by type and date range
  Tasks:
    - [ ] Timeline aggregation API endpoint
    - [ ] Frontend: timeline component with filters
  Story Points: 5

[S-017] Professional Registry
  Acceptance Criteria:
    - Register professionals with council info (CRM, COREN, CRF)
    - Link professional to user account
    - Professional schedule configuration
  Tasks:
    - [ ] Professional model and CRUD
    - [ ] Professional-User linking
    - [ ] Council number validation
  Story Points: 3
```

---

### E-005: Scheduling & Appointments
**Goal:** Complete appointment scheduling with calendar view.
**Dependencies:** E-003

**Stories:**
```
[S-018] Schedule Configuration
  Acceptance Criteria:
    - Configure professional availability (weekday + time blocks)
    - Different slot durations per appointment type
    - Block dates/times (holidays, personal)
  Tasks:
    - [ ] Schedule and TimeSlot models
    - [ ] Availability configuration API
    - [ ] Blocked dates API
    - [ ] Frontend: schedule configuration UI
  Story Points: 5

[S-019] Appointment Booking
  Acceptance Criteria:
    - Book appointment selecting professional, date, time, type
    - No double-booking (PostgreSQL exclusion constraint)
    - Appointment statuses: scheduled → confirmed → waiting → in_progress → completed
    - Source tracking (web, whatsapp, phone, walk-in)
  Tasks:
    - [ ] Appointment model with exclusion constraint
    - [ ] Available slots query API (given professional + date)
    - [ ] Booking API with conflict detection
    - [ ] Status transition API
    - [ ] Frontend: appointment booking page (calendar + slot picker)
    - [ ] Frontend: appointment list/filter view
    - [ ] Frontend: daily agenda view per professional
  Story Points: 8

[S-020] Waiting Room / Queue
  Acceptance Criteria:
    - Real-time waiting list for the day
    - Check-in (arrived) action by receptionist
    - Call patient action by professional
    - Average wait time displayed
  Tasks:
    - [ ] Waiting queue logic
    - [ ] WebSocket or SSE for real-time updates (Django Channels)
    - [ ] Frontend: waiting room dashboard
  Story Points: 5
```

---

### E-006: Billing — TISS/TUSS
**Goal:** Complete TISS-compliant billing with guide generation and glosa management.
**Dependencies:** E-004

**Stories:**
```
[S-021] TUSS Code Database
  Acceptance Criteria:
    - Import official ANS TUSS table (procedures, materials, drugs, fees)
    - Full-text search with fuzzy matching
    - Version tracking (detect ANS updates)
  Tasks:
    - [ ] TUSSCode model
    - [ ] Import management command (CSV → PostgreSQL)
    - [ ] Search API with trigram fuzzy matching
    - [ ] Frontend: TUSS code search component (reusable)
  Story Points: 5

[S-022] TISS Guide Creation
  Acceptance Criteria:
    - Create TISS guides (consultation, SP/SADT, internment, fees)
    - Auto-populate from encounter data
    - Guide numbering (sequential per provider)
    - XML generation following TISS 4.01.00 schema
  Tasks:
    - [ ] TISSGuide and TISSGuideItem models
    - [ ] Guide creation API (auto-populate from encounter)
    - [ ] XML generation engine (Jinja2 templates + XSD validation)
    - [ ] Guide lifecycle (draft → pending → submitted → paid/denied)
    - [ ] Frontend: guide creation/editing form
    - [ ] Frontend: guide list with status filters
  Story Points: 13

[S-023] TISS Batch Submission
  Acceptance Criteria:
    - Group multiple guides into a batch (lote)
    - Generate batch XML file
    - Export XML for manual upload to insurance portal
    - Track batch status
  Tasks:
    - [ ] TISSBatch model
    - [ ] Batch creation API (select guides → generate XML)
    - [ ] XML file stored in MinIO/S3
    - [ ] Download endpoint
    - [ ] Frontend: batch management page
  Story Points: 5

[S-024] Glosa Management
  Acceptance Criteria:
    - Record glosas received from insurance providers
    - Link to specific guide/item
    - Appeal workflow (create appeal, track status)
    - Glosa analytics (top reasons, amounts, providers)
  Tasks:
    - [ ] Glosa model and API
    - [ ] GlosaAppeal workflow
    - [ ] Glosa dashboard with analytics
    - [ ] Frontend: glosa management page
  Story Points: 8

[S-025] Price Tables & Contracts
  Acceptance Criteria:
    - Configure price tables per insurance provider
    - Contract management (validity, covered procedures)
    - Auto-pricing in guides based on contract
  Tasks:
    - [ ] PriceTable, Contract models
    - [ ] Price lookup engine
    - [ ] Frontend: price table configuration
  Story Points: 5
```

---

### E-007: Pharmacy & Inventory
**Goal:** Drug/material catalog, stock management, dispensation linked to prescriptions.
**Dependencies:** E-003, E-004

**Stories:**
```
[S-026] Drug & Material Catalog
  Acceptance Criteria:
    - Drug registry with generic name, commercial name, presentation
    - ANVISA code, controlled substance flag
    - Material registry with category, barcode
  Tasks:
    - [ ] Drug and Material models
    - [ ] CRUD APIs
    - [ ] Fuzzy search (name, generic, barcode)
    - [ ] Controlled substance flagging
    - [ ] Frontend: catalog management pages
  Story Points: 5

[S-027] Stock Management
  Acceptance Criteria:
    - Track stock by item + lot + expiry date
    - All movements are logged (entry, exit, adjustment, loss)
    - Min/max stock alerts
    - Expiry alerts (30/60/90 days before)
  Tasks:
    - [ ] StockItem and StockMovement models
    - [ ] Stock entry API (manual + purchase order)
    - [ ] Stock query API (current levels, by location)
    - [ ] Celery task: expiry alert checker (daily)
    - [ ] Celery task: min stock alert checker (daily)
    - [ ] Frontend: stock dashboard with alerts
    - [ ] Frontend: stock movement history
  Story Points: 8

[S-028] Dispensation
  Acceptance Criteria:
    - Dispense medication from prescription
    - Stock automatically decremented
    - Controlled substance additional validation
    - Dispensation record linked to prescription + patient + lot
  Tasks:
    - [ ] Dispensation model and API
    - [ ] Stock decrement with lot selection (FEFO - First Expiry First Out)
    - [ ] Controlled substance workflow (requires pharmacist)
    - [ ] Frontend: dispensation interface (scan prescription → select lot → confirm)
  Story Points: 8

[S-029] Purchase Orders (basic)
  Acceptance Criteria:
    - Create purchase orders for suppliers
    - Receive goods (creates stock entries)
    - Track order status
  Tasks:
    - [ ] PurchaseOrder, PurchaseOrderItem, Supplier models
    - [ ] PO creation and receiving APIs
    - [ ] Frontend: PO management page
  Story Points: 5
```

---

### E-008: AI — TUSS Auto-Coding
**Goal:** AI suggests TUSS codes from procedure descriptions, reducing billing errors.
**Dependencies:** E-006

**Stories:**
```
[S-030] LLM Integration Layer
  Acceptance Criteria:
    - Abstract LLMGateway interface (Claude + OpenAI)
    - Prompt template versioning system
    - Async execution via Celery
    - Token usage tracking per tenant
    - Cost budgeting per tenant
  Tasks:
    - [ ] LLMGateway abstract class + Claude/OpenAI implementations
    - [ ] AIPromptTemplate model
    - [ ] AIUsageLog model
    - [ ] Celery task for async LLM calls
    - [ ] Rate limiting per tenant (Redis)
    - [ ] Monthly usage report per tenant
  Story Points: 8

[S-031] TUSS Auto-Coding Feature
  Acceptance Criteria:
    - User types procedure description → AI returns top 3 TUSS suggestions with confidence
    - Suggestions validated against TUSS database (no hallucinated codes)
    - User selects or searches manually (AI is assistive, not autonomous)
    - Accepted suggestions cached for reuse
    - Feature behind 'ai_tuss_coding' feature flag
  Tasks:
    - [ ] TUSSCoder service (prompt engineering + output parsing)
    - [ ] Cache layer (same input → same suggestions, Redis TTL 24h)
    - [ ] TUSSAISuggestion model (tracking acceptance rate)
    - [ ] API endpoint: POST /api/v1/ai/tuss-suggest
    - [ ] Frontend: TUSS suggestion component (inline in billing forms)
    - [ ] Tests: verify all suggested codes exist in TUSS DB
  Story Points: 8
```

---

### E-009: WhatsApp — Patient Engagement
**Goal:** Automated appointment scheduling, reminders, and confirmations via WhatsApp.
**Dependencies:** E-005

**Stories:**
```
[S-032] Evolution API Integration
  Acceptance Criteria:
    - Evolution API running in Docker Compose
    - WhatsApp number connected and authenticated
    - Send/receive messages via abstracted WhatsAppGateway
    - Webhook endpoint for incoming messages
  Tasks:
    - [ ] Add evolution-api to docker-compose
    - [ ] WhatsAppGateway interface + EvolutionAPIGateway implementation
    - [ ] Webhook endpoint (POST /api/v1/whatsapp/webhook)
    - [ ] Message sending service (text, template, buttons)
    - [ ] Connection health check
  Story Points: 5

[S-033] Appointment Scheduling Chatbot
  Acceptance Criteria:
    - Patient sends message → bot guides through scheduling flow
    - Flow: greeting → select specialty → select professional → select date → select time → confirm
    - Appointment created in system
    - Confirmation message sent
    - Handles: rescheduling, cancellation
  Tasks:
    - [ ] ConversationFlow state machine
    - [ ] Scheduling flow implementation
    - [ ] Cancellation/rescheduling flow
    - [ ] WhatsAppContact model + opt-in tracking
    - [ ] Patient matching (phone number → patient record)
    - [ ] Error handling + fallback to "speak with attendant"
  Story Points: 13

[S-034] Automated Reminders
  Acceptance Criteria:
    - Reminder sent 24h before appointment
    - Reminder sent 2h before appointment
    - Patient can confirm (👍), reschedule, or cancel with one tap
    - Response updates appointment status
    - Post-visit satisfaction message (optional)
  Tasks:
    - [ ] ScheduledReminder model
    - [ ] Celery Beat task: check reminders due → send messages
    - [ ] Response handler: confirm/reschedule/cancel
    - [ ] Frontend: WhatsApp status visible on appointment list
    - [ ] No-show tracking (sent reminder + no confirm → flag)
  Story Points: 8

[S-035] LGPD Opt-in Management
  Acceptance Criteria:
    - First contact: request opt-in for WhatsApp communications
    - Opt-in stored with timestamp
    - Opt-out at any time ("sair" → stop all messages)
    - No messages sent without opt-in
  Tasks:
    - [ ] Opt-in flow in first conversation
    - [ ] Opt-out handler
    - [ ] Opt-in check before any message sending
  Story Points: 3
```

---

### E-010: Subscription & Feature Flags
**Goal:** Modular pricing system with feature flags per tenant.
**Dependencies:** E-002

**Stories:**
```
[S-036] Feature Flag System
  Acceptance Criteria:
    - Modules gated by feature flags per tenant
    - API endpoints return 403 if module not active
    - Frontend hides UI for inactive modules
    - Admin can toggle modules per tenant
  Tasks:
    - [ ] FeatureFlag middleware (checks subscription → active_modules)
    - [ ] DRF permission class: ModulePermission('billing')
    - [ ] Frontend: useHasModule('billing') hook
    - [ ] Platform admin: toggle modules per tenant
  Story Points: 5

[S-037] Subscription Management
  Acceptance Criteria:
    - Plans with base price + per-module pricing
    - Tenant admin can request module activation
    - Platform admin approves/activates modules
    - Subscription status tracking (active, past_due, cancelled)
  Tasks:
    - [ ] Plan, PlanModule, Subscription models
    - [ ] Subscription CRUD API
    - [ ] Module activation flow
    - [ ] Platform admin panel for subscription management
  Story Points: 8
```

---

### E-013: Workflow Intelligence (Sistema Inteligente)
**Goal:** Make Vitali smart at the seams — every meaningful state change cascades automatically through the right modules. Vitali stops being a database with forms and starts being a system that does things on the user's behalf.

**Why this epic exists:** The competitive moat is not "module count" (Tasy/MV/TOTVS will out-feature us forever). The moat is "this product feels alive." Hire a doctor → access ready in 30 seconds. Sign an encounter → guide drafted, prescription printed, follow-up scheduled. Book an appointment → patient gets WhatsApp confirmation in 2 seconds. Each cascade compounds the AI/automation differentiation.

**Dependencies:** E-002 (Auth/Multi-Tenancy), E-005 (Scheduling), and reuses primitives from E-008 (AI), E-009 (WhatsApp). No new infrastructure required — leverages existing Django signals, Celery + Redis, `appointment_paid` custom signal pattern, and `apps/emr/tasks_waitlist.py` cross-module cascade pattern.

**Stories** (each story = one cascade primitive; a sprint typically ships 1-2):
```
[F-01] Employee/User onboarding cascade  -- Sprint 18
  Trigger: Employee created via /rh/funcionarios
  Cascade: User created (with OTP/invite), role permissions assigned, optional Professional creation, optional WhatsApp staff channel queued
  Story Points: 13

[F-15] User-deactivated cascade  -- Sprint 18 (bundle)
  Trigger: Employee.employment_status = terminated
  Cascade: JWT refresh tokens revoked, API keys revoked, Professional deactivated, WhatsApp channel deactivated
  Story Points: 3

[F-02] Appointment-created cascade  -- Sprint 19
  Trigger: Appointment created
  Cascade: WhatsApp confirmation to patient, slot reserved, optional draft TISS guide if convênio, optional inventory hold for procedure
  Story Points: 5-8

[F-05] DPA-signed cascade  -- Sprint 19
  Trigger: AIDPAStatus.is_signed = True
  Cascade: All AI feature flags enabled atomically, audit log, optional platform admin email
  Story Points: 3

[F-03] Encounter-signed cascade  -- Sprint 20
  Trigger: Encounter status = signed
  Cascade: TISS guide draft auto-generated from procedures, prescription PDFs rendered, post-visit WhatsApp follow-up (24h delay), patient timeline updated
  Story Points: 8-13

[F-04] Patient-registered cascade  -- Sprint 20
  Trigger: Patient created
  Cascade: WhatsAppContact mapping, welcome message, empty medical_history pre-creation, optional CPF Receita Federal validation
  Story Points: 5

[F-06] Stock-low cascade (event-driven)  -- Sprint 21
  Trigger: StockMovement drops StockItem.quantity below min_stock
  Cascade: Real-time alert, draft PurchaseOrder for the affected item with linked supplier
  Story Points: 5

[F-10] Prescription-signed cascade  -- Sprint 21
  Trigger: Prescription signed
  Cascade: PDF link to patient via WhatsApp (with consent gate), pharmacy queue notification, ANVISA report row for controlled meds
  Story Points: 5

[F-11] No-show cascade  -- Sprint 22
  Trigger: Appointment status = no_show
  Cascade: WhatsApp re-engagement, waitlist slot reopened, patient no-show counter increment, refund or reschedule offer
  Story Points: 5

[F-12] AI safety alert cascade  -- Sprint 22
  Trigger: PrescriptionSafetyChecker returns severity=contraindication
  Cascade: Persistent in-app notification to prescriber, audit log of acknowledgment, optional on-call page
  Story Points: 5

[F-14] Module-activated cascade  -- Sprint 23+
  Trigger: Subscription.active_modules adds new module
  Cascade: Module-specific onboarding flow, WhatsApp quick-start link to admin
  Story Points: 5/module
```

**Backlog (post-Sprint 25):** F-16 CID-10 → TUSS pairing (AI deepening, separate epic candidate E-014), F-17 vacation/leave management (HR depth), and ongoing cascade discovery from real pilot usage.

**Reference artifact:** `~/.gstack/projects/tropeks-Vitali/smartness-audit-2026-04-26.md` (full audit + Sprint mapping).

---

## 3. Dependency Graph

```
E-001 Foundation
  └─→ E-002 Auth & Multi-Tenancy
       ├─→ E-003 Patient Management
       │    ├─→ E-004 EMR Clinical Records
       │    │    ├─→ E-006 Billing TISS/TUSS
       │    │    │    └─→ E-008 AI TUSS Auto-Coding
       │    │    ├─→ E-007 Pharmacy & Inventory
       │    │    ├─→ E-011 BI & Analytics [Phase 2]
       │    │    └─→ E-012 DICOM/PACS [Phase 2]
       │    └─→ E-005 Scheduling
       │         └─→ E-009 WhatsApp Engagement
       └─→ E-010 Subscription & Feature Flags
```

---

## 4. Implementation Roadmap

### Sprint 0: Foundation (Weeks 1-2)
**Focus:** Get the skeleton running
- E-001: Full infrastructure setup (Docker, CI/CD, monitoring)
- E-002: S-005 (Tenant registration), S-006 (Auth system)
- **Deliverable:** Working monorepo, Docker Compose up, auth flow functional

### Sprint 1: Auth & Core (Weeks 3-4)
**Focus:** Users can login and manage patients
- E-002: S-007 (RBAC), S-008 (Audit log), S-009 (Frontend auth + layout)
- E-003: S-010 (Patient CRUD)
- **Deliverable:** Login, sidebar navigation, patient registration + search

### Sprint 2: Patient Complete (Weeks 5-6)
**Focus:** Complete patient management
- E-003: S-011 (Insurance data), S-012 (Allergies + history)
- E-004: S-017 (Professional registry)
- E-005: S-018 (Schedule config)
- **Deliverable:** Full patient profile with allergies, insurance, medical history

### Sprint 3: Scheduling (Weeks 7-8)
**Focus:** Appointments working end-to-end
- E-005: S-019 (Appointment booking), S-020 (Waiting room)
- **Deliverable:** Calendar view, appointment booking, waiting room dashboard

### Sprint 4: EMR Core (Weeks 9-11)
**Focus:** Clinical documentation
- E-004: S-013 (Encounters), S-014 (Clinical notes)
- **Deliverable:** Create encounters, record SOAP notes, sign notes

### Sprint 5: Prescriptions (Weeks 12-13)
**Focus:** Prescription workflow
- E-004: S-015 (Prescription builder), S-016 (Patient timeline)
- **Deliverable:** Full prescription builder with drug search, signing, printing

### Sprint 6: Pharmacy (Weeks 14-16)
**Focus:** Inventory and dispensation
- E-007: S-026 (Drug catalog), S-027 (Stock management), S-028 (Dispensation)
- **Deliverable:** Drug catalog, stock tracking, prescription dispensation

### Sprint 7: Billing Foundation (Weeks 17-19)
**Focus:** TISS/TUSS compliance
- E-006: S-021 (TUSS database), S-022 (TISS guide creation), S-025 (Price tables)
- **Deliverable:** TUSS search, guide creation with XML generation

### Sprint 8: Billing Complete (Weeks 20-21)
**Focus:** Batch submission and glosa management
- E-006: S-023 (Batch submission), S-024 (Glosa management)
- **Deliverable:** Complete billing workflow with XML export and glosa tracking

### Sprint 9: AI Layer (Weeks 22-23)
**Focus:** AI infrastructure and TUSS auto-coding
- E-008: S-030 (LLM integration layer), S-031 (TUSS auto-coding)
- **Deliverable:** AI suggests TUSS codes during billing, usage tracking

### Sprint 10: Billing Intelligence Dashboard (Weeks 24-26) ✓ SHIPPED v0.5.0
**Focus:** Analytics and billing intelligence for faturistas (pivoted from WhatsApp)
- S-035: Billing analytics API — 5 aggregate endpoints (overview KPIs, monthly revenue, denial by insurer, batch throughput, Glosa AI accuracy)
- S-036: Billing intelligence frontend page at `/billing/analytics` — KPI cards, charts, period toggle
- S-037: Glosa prediction accuracy tracker — precision/recall per insurer, cold-start onboarding copy
- S-038: TUSS staleness monitor — Celery Beat daily check with INFO/WARNING thresholds
- **Deliverable:** Faturistas have a full billing intelligence dashboard with denial analytics and AI accuracy tracking

### Sprint 11: Commercialization (Weeks 27-28) ✓ SHIPPED v0.6.0
**Focus:** Make it sellable
- E-010: S-039 (Module permission gating), S-040 (Platform admin subscription API), S-041 (Tenant subscription page)
- E-007: S-043 (Purchase orders — Supplier, PO, receiving flow with FEFO stock integration)
- Polish: S-042 (seed_demo_data, demo mode, onboarding widget)
- Infrastructure: Docker networking fix (X-Forwarded-Host tenant routing), catch-all proxy route replacing next.config rewrites
- **Deliverable:** MVP ready for pilot clients — module gating enforced, POs operational, demo-ready

### Sprint 12: WhatsApp Patient Engagement (Weeks 29-31)
**Focus:** Patient communication via WhatsApp (rescheduled from Sprint 10 pivot)
- E-009: S-032 (Evolution API integration), S-033 (Scheduling chatbot), S-034 (Appointment reminders), S-035 (LGPD opt-in)
- **Deliverable:** Patients can schedule and confirm appointments via WhatsApp

---

## 5. Timeline Summary

| Phase | Sprints | Weeks | Deliverable |
|-------|---------|-------|-------------|
| **Foundation** | 0-1 | 1-4 | Auth, tenancy, patient CRUD |
| **Clinical Core** | 2-5 | 5-13 | Scheduling, EMR, prescriptions |
| **Operations** | 6-8 | 14-21 | Pharmacy, billing TISS/TUSS |
| **Intelligence** | 9-10 | 22-26 | AI TUSS coding, Billing Intelligence Dashboard |
| **Commercial** | 11 | 27-28 | Module gating, subscriptions, purchase orders, pilot polish |
| **Engagement** | 12 | 29-31 | WhatsApp patient scheduling & reminders |

**Total estimated: ~7 months to MVP** (solo dev + AI, full-time)

---

## 6. Post-MVP Phases

### Phase 2 (Months 8-12)
- E-011: BI & Analytics (Apache Superset integration) — Sprint 10 shipped the
  Billing Intelligence Dashboard (`/billing/analytics`) which covers the
  built-in BI surface; full Superset embedding is the optional infrastructure
  layer.
- E-012: DICOM/PACS (Orthanc + OHIF Viewer) — **tracking primitive shipped
  2026-05-20** (`apps.imaging`): `DicomStudy` model keyed by DICOM
  `study_instance_uid`, REST for CRUD + Orthanc-UID backfill, gated by
  FeatureFlag `imaging` (default OFF). Remaining: Orthanc deployment +
  webhook handler that auto-populates `orthanc_study_id`, OHIF Viewer
  frontend embed.
- AI Clinical Safety Net (prescription error detection) — **shipped** in
  Sprint 15 as S-063 (PrescriptionSafetyChecker).
- AI Scribe (clinical documentation automation) — **shipped** in the Sprint
  15-17 catch-up (Whisper service + `views_scribe.py` + scribe UI).
- MFA for admin/medical roles — **shipped** in Sprint 15 as S-062 (TOTP +
  backup codes + `/profile/security`).
- ICP-Brasil digital signature integration — **primitive shipped 2026-05-20**
  (`apps.signatures`): A1 PKCS#12 load + SHA-256/RSA sign + verify +
  tenant-scoped `DigitalSignature` storage, gated by FeatureFlag
  `signatures`. Remaining: full DOC-ICP-04 chain-of-trust validation, A3
  hardware-token support, and integration into encounter / prescription
  sign flows.

### Phase 3 (Year 2)
- Telemedicina module — **session tracking primitive shipped 2026-05-20**
  (`apps.telemedicine`): `TelemedicineSession` model with
  `scheduled → in_progress → completed | cancelled` state machine,
  `room_uid` for the eventual WebRTC routing layer, recording URL slot,
  REST with explicit transition endpoints (CFM Res. 2.314/2022 §3 audit
  trail), FeatureFlag `telemedicine` (default OFF). Remaining: WebRTC
  signalling infra (Janus/Jitsi), TURN/STUN deployment, video recording
  pipeline with encryption-at-rest, frontend video UI.
- Portal do Paciente — **shipped end-to-end 2026-05-20**:
  - **Backend** (`apps.patient_portal`): `PatientPortalAccess` model with
    invite-token state machine, admin surface for clinic staff (mint /
    revoke), and self-data surface
    (`/portal/me/profile/appointments/encounters/prescriptions/allergies`)
    gated by `IsPortalSelfAccess`. Module key `patient_portal` (default
    OFF).
  - **Frontend** (`frontend/app/portal/*`): Next.js patient app sharing
    the staff build, but with isolated auth and layout. Public pages
    `/portal/login` + `/portal/activate`; protected pages under
    `(protected)/` for home dashboard, consultas, prontuário, receitas,
    alergias, perfil. Patient-friendly status labels via
    `frontend/lib/portal-status.ts` (e.g. prescription `signed` →
    "Pronta para retirar") over the canonical operational palette.
    Typed fetch client `frontend/lib/portal-api.ts` with error classes
    routing 401 → login and 403 → activate.
  - Remaining: invite-delivery integration (sending the invite_token
    via WhatsApp / e-mail — the token is generated and stored, only the
    notification channel is missing).
- Smart Scheduling (AI-optimized) — **rule-based primitive shipped
  2026-05-20** (`apps.smart_scheduling`): slot ranker over
  `ScheduleConfig` + `Appointment` history with three explicit signals
  (clinical-time / gap-fill / patient-history); REST
  `GET /api/v1/scheduling/suggest/`; module key `smart_scheduling`
  (default OFF). Determinism + per-signal explanation keep the primitive
  audit-friendly. Remaining: learned model trained on accumulated
  no-show + attendance data.
- Triagem Inteligente (WhatsApp) — **FSM primitive shipped 2026-05-20**
  (`apps.triage`): TriageSession state machine + 6-question red-flag
  bank + deterministic `routine / urgent / emergency` evaluator with
  CFM Res. 2.314/2022 §6 auto-escalation on emergency; REST under
  `/api/v1/triage/`; module key `triage` (default OFF). Remaining:
  WhatsApp message-routing integration that turns each inbound message
  into an `answer()` call and each `current_question` into an outbound
  WhatsApp send.
- AI Farmácia (demand prediction) — **baseline forecast primitive shipped
  2026-05-20** (`apps.pharmacy_ai`): rolling-window arithmetic forecast
  over `StockMovement` ledger; REST
  `GET /api/v1/pharmacy/forecast/?drug=…&window_days=…&target_days=…`;
  module key `pharmacy_ai` (default OFF). Remaining: seasonality-aware ML
  model trained on accumulated dispensation history (clinical data first,
  then model).
- Multi-country compliance (start with Portugal/Angola) — **i18n
  *scaffolding* shipped 2026-05-20, but no translation is actually served
  yet**: Django `LANGUAGES` advertises pt-BR / pt-PT / es / en,
  `LOCALE_PATHS` points at four `locale/<code>/LC_MESSAGES/` stub
  directories (currently empty — only `.gitkeep`, zero `.po`/`.mo`
  catalogs), and the request plumbing is real (per-user
  `preferred_language` field, `PreferredLanguageMiddleware`,
  `GET / PATCH /api/v1/users/me/language/`). However, source strings are
  **not** yet `gettext`-marked (one lone `gettext_lazy` import in
  `apps/core/admin.py`) and the catalogs are empty, so the platform
  effectively serves **pt-BR only** regardless of the selected language.
  Real multi-language is a Phase 3 epic — see `docs/I18N.md` for the
  phased plan. Remaining: mark every user-facing string with
  `gettext`/`gettext_lazy`; generate, translate and compile the catalogs;
  add a frontend i18n library (the Next.js UI has none today) and extract
  hardcoded JSX strings; locale-aware date / number formatting in clinical
  screens; per-country regulatory regimes (PT, AO).
- FHIR API for interoperability — **8 of 8 resources shipped 2026-05-20**
  (`apps.fhir`). The interop primitive is feature-complete at the
  resource-coverage level documented here:
  - Patient resource (read + identifier/name search) — DONE.
  - Encounter resource (read + subject/status search, ambulatory class) —
    DONE.
  - Practitioner resource (read + identifier/name/active search; closes
    the `Practitioner/<id>` references emitted by Encounter participants)
    — DONE.
  - AllergyIntolerance resource (criticality from severity, clinical +
    verification status, reaction sub-element) — DONE.
  - MedicationRequest resource (one per PrescriptionItem,
    `groupIdentifier` carries parent prescription uuid) — DONE.
  - Observation resource (one per vital sign per VitalSigns row, with
    stable LOINC codes for weight/height/BP/HR/temp/SpO₂/BMI) — DONE.
  - Condition resource (CID-10 / ICD-10 coding, category derived from
    Vitali type, controlled-status rolled into active with a note) —
    DONE.
  - ServiceRequest resource (referrals + exam requests with SNOMED
    category coding, status derived from signature) — DONE.
  - Capability Statement advertises all eight resources.
  Follow-up (out of the documented FHIR scope): full Bundle semantics with
  paging links; SMART-on-FHIR auth profile; additional resource types
  (DocumentReference, DiagnosticReport, Coverage, etc.) as new integration
  partners require them.
- Mobile app (React Native, sharing codebase) — **backend primitive
  shipped 2026-05-20** (`apps.mobile`): `MobileDevice` registration +
  `PushDelivery` audit log + `MobilePushService` with a pluggable
  `PushAdapter` protocol (FCM/APNS adapter slots in without view or test
  changes); module key `mobile` (default OFF); REST under
  `/api/v1/mobile/`. Remaining: the React-Native client project itself
  (setup, auth flow, screens, build pipeline) and the FCM/APNS adapter
  implementation. The backend that mobile apps need is complete; the
  app project is the parallel work.

---

*This roadmap is a living document. Priorities may shift based on pilot client feedback.*
