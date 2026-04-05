<!-- /autoplan restore point: /home/rcosta00/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260405-181126.md -->
<!-- autoplan: tropeks-Vitali / master / afe1fb3 / 2026-04-05 -->

# Sprint 14 Plan — First Pilot Readiness (v0.9.0)

**Branch:** master
**Sprint:** 14
**Epic:** E-014 — First Pilot Readiness
**Stories:** S-054 through S-061
**Total points:** TBD (to be confirmed by autoplan)
**Target version:** v0.9.0

---

## Goal

Everything needed for a real pilot clinic to use Vitali end-to-end. After this sprint: a clinic admin can onboard via a guided wizard, patients can pay via PIX for self-pay appointments, appointment confirmations arrive by email, we have realistic demo data for investor demos, the 5 slowest queries are indexed, critical pages render on mobile, non-technical clinic staff have a task-oriented user guide, and the founding team has a real-time dashboard to support the pilot.

**Explicit out-of-scope (initial):**
- PIX split payments or multi-beneficiary (Phase 2)
- Full MFA / TOTP (Phase 2)
- Patient-facing mobile app (Phase 2)
- Enterprise SSO / SAML (Phase 2)

---

## Stories

### S-054 — Tenant Onboarding Wizard (8 pts)

**Rationale:** Right now, activating a new clinic requires direct DB access, Django admin manipulation, and manual schema creation. That is a blocker for any pilot — you cannot hand a clinic admin a URL and have them be productive in 5 minutes. This wizard is the difference between "we can do a pilot" and "we need an engineer on-site."

**Scope:**
- Backend: `POST /api/v1/platform/onboarding/` — creates Tenant + Domain + first admin User in public schema; returns JWT for immediate login
- Backend: `POST /api/v1/setup/working-hours/` — bulk-sets ScheduleConfig for a professional (Mon-Fri defaults)
- Backend: `POST /api/v1/setup/professionals/` — creates Professional + linked User in tenant schema
- Frontend: 4-step wizard at `/setup` (accessible only if clinic has no professionals yet):
  - Step 1: Clinic name, slug, CNPJ
  - Step 2: First admin (name, email, password)
  - Step 3: Working hours (visual week-grid, Mon-Fri 08:00-18:00 defaults, lunch break)
  - Step 4: First professional + specialty (auto-adds current user as professional if admin is a doctor)
- Wizard guards: if `Professional.objects.exists()` → redirect to dashboard (idempotent)
- Tests: `test_onboarding_creates_tenant_and_admin`, `test_wizard_redirects_if_already_configured`

**Files touched:**
- `backend/apps/core/views.py` + `backend/apps/core/urls.py` (new platform endpoint)
- `backend/apps/emr/views.py` + `backend/apps/emr/urls.py` (setup endpoints)
- `frontend/app/setup/` (new wizard pages)
- `frontend/app/setup/layout.tsx`
- `frontend/app/setup/page.tsx` (step 1: clinic)
- `frontend/app/setup/working-hours/page.tsx`
- `frontend/app/setup/professional/page.tsx`

---

### S-055 — PIX Payment Integration — Asaas (13 pts)

**Rationale:** The existing billing module is TISS/health-insurance-only. Self-pay patients (a significant portion of Brazilian clinics — especially smaller ones and pilot clinics) have no way to pay. We need PIX because it is the dominant payment method in Brazil (80%+ of digital transactions). Asaas is the standard Brazilian payment gateway with a PIX-first API and good sandbox.

**Scope:**
- Backend: `PIXCharge` model per-tenant with fields: `appointment`, `amount`, `asaas_charge_id`, `status` (pending/paid/expired/refunded), `pix_copy_paste`, `pix_qr_code_base64`, `expires_at`
- Backend: `AsaasService` — `create_pix_charge(appointment)`, `cancel_charge(charge_id)`, `get_charge_status(charge_id)`
- Backend: `POST /api/v1/billing/pix/charges/` — create charge for appointment
- Backend: `POST /api/v1/billing/pix/webhook/` — Asaas webhook receiver (validates `asaas-access-token` header, updates charge status, fires `appointment_paid` signal)
- Signal handler: `on_appointment_paid` — updates `Appointment.status` to `confirmed`, triggers confirmation email (S-056)
- Frontend: PIX QR code modal in appointment detail page — show QR + copy-paste + countdown timer
- `.env.staging.example` additions: `ASAAS_API_KEY`, `ASAAS_WEBHOOK_TOKEN`, `ASAAS_ENVIRONMENT` (sandbox/production)
- Tests: `test_create_pix_charge`, `test_webhook_marks_paid`, `test_expired_charge_does_not_confirm_appointment`

**Security:**
- Webhook token validated via constant-time comparison (`hmac.compare_digest`)
- Asaas API key stored in env, never logged
- QR code expires in 30 minutes (configurable via `PIX_CHARGE_EXPIRY_MINUTES` env)

**Files touched:**
- `backend/apps/billing/models.py` (PIXCharge model)
- `backend/apps/billing/services/asaas.py` (new service)
- `backend/apps/billing/views.py` + `backend/apps/billing/urls.py`
- `backend/apps/billing/signals.py`
- `backend/apps/billing/migrations/`
- `frontend/app/(dashboard)/appointments/[id]/` (PIX modal)
- `.env.staging.example`

---

### S-056 — Transactional Email — Appointment Confirmations (5 pts)

**Rationale:** Email is configured (SendGrid SMTP in production.py) but no emails are sent. Appointment confirmations are the highest-value transactional email for a clinic — they reduce no-shows. A pilot clinic will ask "does it send confirmations?" on day one.

**Scope:**
- Backend: `EmailService` in `apps/core/services/email.py` — wraps `django.core.mail.send_mail` + Jinja2 template rendering
- Templates: `backend/templates/email/appointment_confirmation.html` (Portuguese, mobile-friendly, clinic logo placeholder)
- Templates: `backend/templates/email/appointment_reminder.html` (sent 24h before via Celery beat)
- Signal receiver: on `Appointment.status` → `confirmed` (from PIX webhook or manual confirm), send confirmation email async via Celery
- Celery beat task: `send_appointment_reminders` — daily at 08:00, sends 24h-ahead reminders
- Frontend: email preview in `/configuracoes` showing what the confirmation email looks like
- Tests: `test_confirmation_email_sent_on_confirm`, `test_reminder_task_targets_tomorrows_appointments`

**Files touched:**
- `backend/apps/core/services/email.py` (new)
- `backend/templates/email/appointment_confirmation.html` (new)
- `backend/templates/email/appointment_reminder.html` (new)
- `backend/vitali/celery.py` (beat schedule addition)
- `backend/apps/emr/signals.py` (confirmation trigger)

---

### S-057 — Seed Data Make Target (2 pts)

**Rationale:** `seed_demo_data` management command exists (S-043) but there is no `make seed-demo` target and the command lacks appointment data (future dates). Investor demo requires seeing a populated schedule.

**Scope:**
- Add `seed-demo` target to `Makefile` (or create `Makefile` if missing): `docker compose exec django python manage.py seed_demo_data --tenant=demo`
- Enhance `seed_demo_data` command:
  - Add `Appointment` records: 10 future appointments (next 7 days) + 5 past (for analytics)
  - Add `PIXCharge` records: 3 paid, 2 pending
  - Add `ScheduleConfig` with realistic working hours for demo professional
- Idempotency: appointment seeding checks `[DEMO]` prefix on patient name (already in place)

**Files touched:**
- `Makefile` (create or update)
- `backend/apps/core/management/commands/seed_demo_data.py`

---

### S-058 — Performance Audit: Top 5 Slow Queries + Indexes (5 pts)

**Rationale:** With no real load data, we identify slow queries from code review (N+1 patterns, missing indexes on FK + filter columns). Adding targeted indexes before the pilot means we do not debug performance under load during a demo.

**Analysis of likely slow queries (from code review):**

1. `Appointment.objects.filter(start_time__date=today)` — `start_time` is indexed but `date()` extraction bypasses it. Add partial function index.
2. `TISSGuide.objects.filter(batch__provider=provider, status='pending')` — no composite index on `(batch_id, status)`.
3. `Patient.objects.filter(insurance_data__contains=...)` — JSONField query with no GIN index.
4. `Encounter.objects.filter(professional=p, encounter_date__gte=start)` — `encounter_date` has index but `professional+encounter_date` composite is missing.
5. `AuditLog.objects.filter(tenant_schema=schema, action=action)` — no composite index.

**Scope:**
- Django migrations adding indexes for each of the 5 patterns above
- `db_index` on `TISSGuide.status` + composite `(batch, status)`
- GIN index on `Patient.insurance_data` (JSONField)
- Composite `(professional, encounter_date)` on Encounter
- `(tenant_schema, action)` on AuditLog
- `EXPLAIN ANALYZE` commands documented in `docs/PERFORMANCE.md`

**Files touched:**
- `backend/apps/emr/migrations/` (new migration)
- `backend/apps/billing/migrations/` (new migration)
- `backend/apps/core/migrations/` (new migration)
- `backend/apps/emr/models.py` (index declaration)
- `backend/apps/billing/models.py` (index declaration)
- `backend/apps/core/models.py` (AuditLog index)
- `docs/PERFORMANCE.md` (new, EXPLAIN ANALYZE examples)

---

### S-059 — Mobile Responsiveness Pass (5 pts)

**Rationale:** Clinic staff use tablets and phones. The three most-used pages — appointments list, weekly schedule, and WhatsApp settings — must be usable on a 375px-wide screen before the pilot.

**Scope:**
- Appointments list (`/appointments`): responsive table → card list below 768px
- Weekly schedule (`/appointments/schedule` or similar): horizontal scroll + day-view toggle on mobile
- WhatsApp settings (`/configuracoes/whatsapp`): form layout stacks vertically on mobile
- No new UI components — use existing Tailwind responsive prefixes (`sm:`, `md:`, `lg:`)
- Test: screenshot at 375px for each page (manual/visual, documented in PR)

**Files touched:**
- `frontend/app/(dashboard)/appointments/page.tsx`
- `frontend/app/(dashboard)/appointments/schedule/page.tsx` (if exists)
- `frontend/app/(dashboard)/configuracoes/whatsapp/page.tsx`
- Any shared layout components used in those pages

---

### S-060 — User Guide (docs/USER_GUIDE.md) (3 pts)

**Rationale:** Clinic admin is non-technical. They need a guide that says "to add a patient, click X" — not a data model description. This ships with the pilot so we do not answer the same 10 questions by WhatsApp every day.

**Scope:** `docs/USER_GUIDE.md` with these sections:
1. First login and setup wizard walkthrough (with step descriptions)
2. Adding a patient
3. Booking an appointment
4. The waiting room view
5. Completing an encounter (SOAP notes)
6. Generating a TISS batch
7. Receiving a PIX payment
8. Sending a WhatsApp message / appointment reminder
9. Reading your analytics dashboard
10. Getting support (contact info placeholder)

Each section: 3-5 steps, plain Portuguese, no technical jargon.

**Files touched:**
- `docs/USER_GUIDE.md` (new)

---

### S-061 — First-Pilot Monitoring Dashboard (8 pts)

**Rationale:** When the pilot goes live, the founding team needs to see what is happening in real time — not by SSHing into the server. This is a separate operator view (not the clinic's own analytics). Key questions: Is the clinic actively using it? Are errors happening? Are appointments being booked?

**Scope:**
- Backend: `GET /api/v1/platform/pilot-health/` — platform-staff-only endpoint (requires `is_staff=True`) returning:
  - `active_tenants`: list of tenants with `last_activity` (last API request timestamp), `appointments_today`, `errors_today` (from Sentry tag counts, or Django log count)
  - `system_health`: Celery queue depth, Redis ping, DB connection pool usage
  - `recent_errors`: last 10 Sentry events (if `SENTRY_DSN` configured) or last 10 ERROR log lines
- Frontend: `/platform/monitor` — staff-only page (guarded by `user.is_staff`):
  - Tenant activity table (sortable by last_activity)
  - System health status pills (green/yellow/red)
  - Error stream (last 10, auto-refresh every 30s)
  - Appointment volume sparkline (today by hour)
- Auth guard: `user.is_staff` check server-side + middleware redirect
- Tests: `test_pilot_health_requires_staff`, `test_pilot_health_returns_expected_fields`

**Files touched:**
- `backend/apps/core/views.py` (platform health endpoint)
- `backend/apps/core/serializers_platform.py` (new serializer)
- `backend/apps/core/urls_public.py` (new route)
- `frontend/app/platform/monitor/page.tsx` (new)
- `frontend/app/platform/layout.tsx` (new, staff guard)

---

## What Already Exists (do NOT rebuild)

| Sub-problem | Existing code |
|---|---|
| Seed data logic | `backend/apps/core/management/commands/seed_demo_data.py` |
| Analytics KPIs | `backend/apps/analytics/views.py` — `OverviewView`, `ProfessionalStatsView` |
| Email SMTP config | `backend/vitali/settings/production.py:68-74` |
| Appointment indexes | `backend/apps/emr/models.py:222-226` — `professional+start_time`, `patient+start_time`, `status+start_time` |
| Celery worker | `backend/vitali/celery.py` + docker-compose |
| Tenant model | `backend/apps/core/models.py:Tenant` |
| Working hours model | `backend/apps/emr/models.py:ScheduleConfig` |
| Professional model | `backend/apps/emr/models.py:Professional` |
| WhatsApp settings page | `frontend/app/(dashboard)/configuracoes/whatsapp/` |

---

## NOT In Scope

- Full patient-facing portal (Phase 2)
- PIX refunds UI (API exists via Asaas, frontend deferred)
- Mercado Pago integration (Asaas chosen — better Brazilian clinic fit)
- Push notifications / PWA
- Multi-language support (Portuguese only)
- Automated performance regression testing (Sprint 15)
- Advanced pilot analytics (cohort retention, churn signals) — Sprint 15

---

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|---------|
| 1 | CEO | Keep email (S-056) alongside WhatsApp | Mechanical | P3 | Email required for legal receipts in BR healthcare; WhatsApp has reminders; complementary channels | Swap S-056 for WhatsApp expansion |
| 2 | CEO | Asaas over Mercado Pago (S-055) | Mechanical | P3 | Asaas PIX-first API, simpler webhook, better SMB clinic fit | Mercado Pago |
| 3 | CEO | Add admin re-run endpoint in S-054 | Mechanical | P2 | Blast radius same files; prevents engineer DB edit on misconfigured clinics | Hard guard only |
| 4 | CEO | Add behavioral KPIs to S-061 | Mechanical | P2 | In blast radius; pilot success visibility at zero extra model cost | Ops-only dashboard |
| 5 | CEO | Add "AI em breve" section to USER_GUIDE | Mechanical | P2 | In blast radius; positioning + retention for pilot clinic | Docs without AI mention |
| 6 | CEO | S-055 must use Asaas customer ID not raw CPF | Mechanical | P1 | LGPD — CPF is sensitive PII, must not leave system in raw form | Direct CPF transmission |
| 7 | CEO (GATE) | Keep PIX S-055 | USER CONFIRMED | User judgment | Pilot clinic has self-pay volume | Defer or slim PIX |
| 8 | Design | Wizard Step 1: Name first, CNPJ last, slug → "identificador URL" | Mechanical | P5 | Clinic admin doesn't know "slug"; CNPJ abandonment risk | CNPJ/slug first |
| 9 | Design | Add Step 5 completion screen to wizard | Mechanical | P1 | No completion state; user doesn't know setup is done | Silent redirect |
| 10 | Design | Step 3 working hours: click-to-toggle per hour (not drag grid) | Mechanical | P5 | Drag ambiguous on touch; explicit interaction | Drag grid |
| 11 | Design | PIX modal: mobile = "Copiar" primary CTA, QR collapsed | Mechanical | P5 | User can't scan own screen; copy-paste is primary on mobile | QR primary always |
| 12 | Design | PIX modal: 5s polling, max 6 attempts, then "verifique com a clínica" | Mechanical | P5 | Explicit post-payment behavior; no infinite spinner | No polling spec |
| 13 | Design | PIX expiry: "QR expirado — gerar novo?" button | Mechanical | P1 | Expiry action required; generate-new is the only valid UX | Auto-close on expiry |
| 14 | Design | Dashboard: "Atualizado às HH:MM:SS" + stale banner on fetch failure | Mechanical | P1 | User can't know if data is stale without timestamp | Silent refresh |
| 15 | Design | Dashboard sparkline: tenant local time, auto y-axis min=5, zero-state text | Mechanical | P5 | UTC sparkline wrong for BR clinics; zero-state prevents broken chart | UTC / fixed y-axis |
| 16 | Design | Appointment card (mobile): patient name, time, status, one action button | Mechanical | P5 | Implementer needs explicit field list for card layout | Arbitrary design |
| 17 | Eng | PIX webhook: public-schema AsaasChargeMap(tenant_schema, asaas_charge_id) | Mechanical | P5 | Explicit tenant resolution; no schema scanning | Scan all schemas |
| 18 | Eng | Webhook handler: select_for_update + status-check idempotency guard | Mechanical | P1 | Asaas at-least-once delivery; prevents double email/status | No idempotency |
| 19 | Eng | PIX webhook: verify charge exists in DB before acting | Mechanical | P1 | Static token leak risk; charge-existence check prevents forged confirms | Static token only |
| 20 | Eng | Signal handler enqueues send_confirmation_email.delay(), never inline | Mechanical | P5 | Signal in DB transaction; Celery failure must not roll back transaction | Inline send_mail |
| 21 | Eng | start_time__date index: RunSQL timezone-aware function index | Mechanical | P5 | models.Index doesn't fix __date extract; needs AT TIME ZONE function index | models.Index |
| 22 | Eng | Asaas charge cancellation: Celery beat task at expires_at | Mechanical | P1 | Client-side timer only; Asaas may still process late payments | Frontend countdown only |
| 23 | Eng | Onboarding view: get_or_create + unique constraint on slug | Mechanical | P5 | Double-click creates two tenants → unhandled 500 | No race protection |
| 24 | Eng | Pilot health endpoint: explicit schema_context() loop | Mechanical | P5 | Appointment counts must query tenant schemas explicitly | Naive public query |
| 25 | Eng | Add Celery beat service to docker-compose.staging.yml | Mechanical | P1 | Beat task for reminders never runs without beat worker | Undocumented dependency |
| 26 | Eng | EmailService skips empty recipient list gracefully | Mechanical | P1 | patient.email == "" crashes send_mail; guard with early return | Crash on blank email |
| 27 | DX | Add Asaas env vars to .env.example with sandbox defaults | Mechanical | P5 | New engineer must not get a KeyError crash | .env.staging.example only |
| 28 | DX | AsaasService raises ImproperlyConfigured with docs link if key missing | Mechanical | P5 | Explicit error > mystery crash | KeyError |
| 29 | DX | Add Local PIX Setup section to docs/DEVELOPMENT.md | Mechanical | P1 | TTHW drops from 45min to 10min | No local setup docs |
| 30 | DX | Rename /api/v1/platform/onboarding/ → /api/v1/platform/tenants/ | Mechanical | P5 | Verb-in-path inconsistent with REST convention | Verb path |
| 31 | DX | Add seed-demo, makemigrations, bash, superuser to Makefile help + .PHONY | Mechanical | P5 | Undiscoverable commands | Missing from help |
| 32 | DX | AsaasService HTTP calls: 5s timeout, structured error response | Mechanical | P5 | Error contract enables actionable frontend messages | Unspecified timeout |
