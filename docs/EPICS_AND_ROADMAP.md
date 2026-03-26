# HealthOS — Epics, Stories & Roadmap

> **Refs:** [PROJECT_BRIEF.md](./PROJECT_BRIEF.md) | [ARCHITECTURE.md](./ARCHITECTURE.md) |
> [DATA_MODEL.md](./DATA_MODEL.md)

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

### Sprint 10: WhatsApp (Weeks 24-26)
**Focus:** Patient engagement via WhatsApp
- E-009: S-032 (Evolution API), S-033 (Scheduling chatbot), S-034 (Reminders), S-035 (LGPD opt-in)
- **Deliverable:** Patients schedule and confirm via WhatsApp

### Sprint 11: Commercialization (Weeks 27-28)
**Focus:** Make it sellable
- E-010: S-036 (Feature flags), S-037 (Subscription management)
- E-007: S-029 (Purchase orders)
- Polish: onboarding flow, demo mode, landing page
- **Deliverable:** MVP ready for pilot clients

---

## 5. Timeline Summary

| Phase | Sprints | Weeks | Deliverable |
|-------|---------|-------|-------------|
| **Foundation** | 0-1 | 1-4 | Auth, tenancy, patient CRUD |
| **Clinical Core** | 2-5 | 5-13 | Scheduling, EMR, prescriptions |
| **Operations** | 6-8 | 14-21 | Pharmacy, billing TISS/TUSS |
| **Intelligence** | 9-10 | 22-26 | AI TUSS coding, WhatsApp |
| **Commercial** | 11 | 27-28 | Feature flags, subscriptions, polish |

**Total estimated: ~7 months to MVP** (solo dev + AI, full-time)

---

## 6. Post-MVP Phases

### Phase 2 (Months 8-12)
- E-011: BI & Analytics (Apache Superset integration)
- E-012: DICOM/PACS (Orthanc + OHIF Viewer)
- AI Clinical Safety Net (prescription error detection)
- AI Scribe (clinical documentation automation)
- MFA for admin/medical roles
- ICP-Brasil digital signature integration

### Phase 3 (Year 2)
- Telemedicina module
- Portal do Paciente
- Smart Scheduling (AI-optimized)
- Triagem Inteligente (WhatsApp)
- AI Farmácia (demand prediction)
- Multi-country compliance (start with Portugal/Angola)
- FHIR API for interoperability
- Mobile app (React Native, sharing codebase)

---

*This roadmap is a living document. Priorities may shift based on pilot client feedback.*
