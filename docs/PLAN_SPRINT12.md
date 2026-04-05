<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260405-092505.md -->
# Sprint 12 — WhatsApp Patient Engagement

**Status:** APPROVED
**Date:** 2026-04-05
**Branch:** feature/sprint12-whatsapp
**Epics:** E-009 (WhatsApp — Patient Engagement)
**Target users:** Patients (via WhatsApp), Recepcionista (via frontend), Clinic admin
**Success metrics:**
- Primary: ≥60% of sent reminders result in explicit confirmation or reschedule (vs current ~0% automated)
- Secondary: No-show rate drops ≥20% relative to pilot clinic baseline (measure before Sprint 12 ships)
- Operational: Receptionists spend <5 min/day managing WhatsApp conversations (vs current manual calling)
**Differentiation:** Standalone WhatsApp reminder bots are commodity. Vitali's moat is integration — reminders know the doctor's name, the specialty, the appointment time, the patient's history. Competitors can't send "Sua consulta com Dr. Silva para retorno de cirurgia está confirmada amanhã às 14h" — they send generic "Appointment reminder." This is the reason to build it inside the platform.

---

## Context

Sprint 11 shipped the commercialization layer — module gating, subscriptions, purchase orders, demo mode. Vitali is pilot-ready.

The gap: patient engagement is phone-only. Receptionists manually call patients for reminders, confirmations, and rescheduling. No-show rates are high and staff time is wasted.

Sprint 12 closes this gap. Four stories from E-009:

**S-032 — Evolution API Integration:** Self-hosted Evolution API running in Docker Compose, abstracted behind `WhatsAppGateway`. Webhook endpoint receives incoming messages from patients. Message sending service for text, templates, and button menus.

**S-033 — Appointment Scheduling Chatbot:** State machine that guides a patient through booking an appointment via WhatsApp. Flow: greeting → specialty selection → professional selection → date/slot selection → confirmation → appointment created in system.

**S-034 — Automated Reminders:** Celery Beat task sends appointment reminders 24h and 2h before each appointment. Patient responds with one tap (confirm/reschedule/cancel). Response updates appointment status. No-show tracking.

**S-035 — LGPD Opt-in Management:** First contact from a new phone number triggers opt-in request. Opt-in stored with timestamp. "Sair" at any time triggers opt-out. No messages sent without explicit opt-in.

---

## What Already Exists (Don't Rebuild)

| Sub-problem | Existing code |
|---|---|
| WhatsApp app skeleton | `apps.whatsapp` (AppConfig only, no models yet) |
| Patient phone/WhatsApp field | `Patient.phone` (CharField) + `Patient.whatsapp` (CharField, indexed) |
| Appointment model | `emr.Appointment` with `whatsapp_reminder_sent`, `whatsapp_confirmed` flags, `source='whatsapp'` choice |
| Schedule/slot config | `emr.ScheduleConfig` (per-professional slot config) |
| Celery infrastructure | Worker + Beat already in Docker Compose, `django_celery_beat` scheduler |
| Redis | Running at `redis://redis:6379/0` |
| Module key | `'whatsapp'` in `ALLOWED_MODULE_KEYS` (core.constants) |
| Feature flag model | `core.FeatureFlag` + `ModuleRequiredPermission` |
| RBAC | `HasPermission` + roles (recepcionista, admin) |
| Audit log | `_write_audit()` in core.signals |

**NOT in scope:**
- WhatsApp Business API (official Meta API) — Evolution API only for Sprint 12
- LLM/AI-powered freeform NLP — keyword intent detection only (no Claude API call)
- Patient portal web app — WhatsApp only
- Video/image message sending
- Multi-language support (PT-BR only)
- Payment collection via WhatsApp
- Prescription ready notifications (deferred — crosses pharmacy module boundary)
- Recurring follow-up reminders (deferred — requires appointment history analysis)
- Bulk broadcast to all opted-in patients (deferred — new UI surface, separate feature)

---

## Stories

### S-032 — Evolution API Integration
**Acceptance Criteria:**
- Evolution API container runs in Docker Compose, accessible at `http://evolution-api:8080`
- `WhatsAppGateway` abstract interface with `EvolutionAPIGateway` implementation
- `POST /api/v1/whatsapp/webhook` endpoint validates HMAC signature and dispatches messages
- `send_text(to, text)`, `send_template(to, template_name, params)`, `send_button_menu(to, body, buttons)` methods
- Connection health check endpoint

**Tasks:**
- [ ] Add `evolution-api` service to `docker-compose.yml` (image: `atendai/evolution-api:latest`)
- [ ] `WhatsAppGateway` ABC in `apps/whatsapp/gateway.py`
- [ ] `EvolutionAPIGateway` implementation (requests-based, env-configured)
- [ ] `POST /api/v1/whatsapp/webhook` view with HMAC-SHA256 validation
- [ ] Webhook dispatcher: route by message type (text, button_reply, list_reply)
- [ ] Health check view `GET /api/v1/whatsapp/health/`
- [ ] Add `requests>=2.32` to `backend/requirements/base.txt` (not currently installed)
- [ ] `WHATSAPP_EVOLUTION_URL`, `WHATSAPP_EVOLUTION_API_KEY`, `WHATSAPP_WEBHOOK_SECRET` to .env.example
- [ ] Unit tests: gateway mock, webhook signature validation, dispatcher routing

**Story Points:** 5

---

### S-033 — Appointment Scheduling Chatbot
**Acceptance Criteria:**
- Patient sends any message → receives greeting + opt-in prompt (if first contact)
- After opt-in: scheduling flow guided by button menus
- Flow: specialty → professional → date (next 7 days) → time slot → confirmation
- Appointment created via existing EMR appointment service
- Handles cancellation (`/cancelar`) and reschedule (`/remarcar`) mid-flow
- Unrecognized input: "Não entendi. Digite /menu para ver as opções."
- Fallback after 3 mismatches: "Prefira falar com nossa equipe: [phone]"

**Tasks:**
- [ ] `WhatsAppContact` model: `phone`, `patient` FK (nullable), `opt_in`, `opt_in_at`, `opt_out_at`
- [ ] `ConversationSession` model: `contact` FK, `state` (IDLE/GREETING/SELECTING_SPECIALTY/...), `context` (JSONField), `expires_at`
- [ ] `ConversationFSM` state machine class (`apps/whatsapp/fsm.py`)
- [ ] Scheduling flow states + transitions
- [ ] Cancellation/reschedule flow
- [ ] Patient matching: `Patient.whatsapp` → `WhatsAppContact` → link patient FK
- [ ] New patient flow: capture name + CPF via WhatsApp, create `Patient` record
- [ ] Appointment creation via `emr.Appointment` model (source='whatsapp')
- [ ] Keyword intent detection: map common PT-BR phrases to intents (`agendar`, `cancelar`, `confirmar`, `remarcar`, `ajuda`, `sair`) before falling back to menu
- [ ] "Booking for someone else" FSM state: after opt-in, ask "É para você ou para outra pessoa?" — if other, capture name/CPF to match or create patient
- [ ] Integration tests: full booking flow, freeform text intent matching, shared-phone booking, cancellation, timeout, fallback

**Story Points:** 16 (was 13, +3 for intent detection + shared-phone flow)

---

### S-034 — Automated Reminders
**Acceptance Criteria:**
- 24h reminder and 2h reminder sent for each confirmed appointment with WhatsApp opt-in
- Reminder buttons: ✅ Confirmar / 📅 Remarcar / ❌ Cancelar
- Button tap updates `Appointment.status` (confirmed/cancelled) and `whatsapp_confirmed`
- Reschedule tap → re-enters scheduling flow at date-selection step
- No-show tracking: appointment with reminder sent but no confirmation → flagged as `no_show` after appointment time passes
- Frontend: WhatsApp badge visible on appointment card (confirmed / reminder sent / pending)

**Tasks:**
- [ ] `ScheduledReminder` model: `appointment` FK, `reminder_type` (24h/2h), `sent_at`, `status`
- [ ] Celery Beat task `send_appointment_reminders`: runs every 15 min, queries upcoming appointments
- [ ] Celery Beat task `mark_no_shows`: runs every hour after appointment end time
- [ ] Button response handler in FSM (confirm/reschedule/cancel)
- [ ] Frontend: `whatsapp_status` field on appointment serializer
- [ ] Frontend badge component on `AppointmentModal.tsx`

**Story Points:** 8

---

### S-035 — LGPD Opt-in Management
**Acceptance Criteria:**
- First message from unknown number → LGPD consent request sent before any other content
- Opt-in captured with timestamp: `WhatsAppContact.opt_in=True`, `opt_in_at=now()`
- "Sair" or "parar" at any point → immediate opt-out, `opt_out_at=now()`, confirmation sent
- No outbound messages sent to contacts where `opt_in=False`
- Admin can view opt-in status in Django admin

**Tasks:**
- [ ] Opt-in flow in `ConversationFSM` (PENDING_OPTIN state)
- [ ] Opt-out command handler (any state)
- [ ] `send_if_opted_in()` guard in `EvolutionAPIGateway`
- [ ] Django admin for `WhatsAppContact` with opt-in status filter
- [ ] Tests: opt-in flow, opt-out mid-conversation, message blocked without opt-in

**Story Points:** 3

---

## Frontend Pages

### WhatsApp Settings (clinic admin)
- `/configuracoes/whatsapp` — QR code to connect WhatsApp number, connection status, instance health
- Conversation history tab: recent message threads per patient (for receptionist debugging)
- Module-gated: `useHasModule('whatsapp')` + role: admin

### Appointment List Enhancement
- WhatsApp status badge on existing appointment cards (already in `/appointments/page.tsx`)
- Green: confirmed via WhatsApp | Yellow: reminder sent | Grey: no WhatsApp

### S-034b — Post-Visit Satisfaction Survey (accepted expansion)
- 2h after appointment status changes to `completed`, send: "Como foi sua consulta? 😊 Muito bom / 😐 Ok / 😕 Poderia ser melhor"
- Response stored on `Appointment.satisfaction_rating` (new nullable IntegerField)
- No-response = no follow-up (not a mandatory interaction)
- Tasks: `ScheduledReminder.reminder_type` choices extended with `'satisfaction'`, Celery Beat task `send_satisfaction_surveys` runs hourly

---

## Architecture

```
Patient (WhatsApp)
        │ sends message
        ▼
Evolution API (Docker)
        │ HTTP webhook POST
        ▼
/api/v1/whatsapp/webhook
        │ HMAC validated
        ▼
WebhookDispatcher
        │
    ┌───┴────────────────┐
    ▼                    ▼
InboundTextHandler  InboundButtonHandler
        │                │
        └────────┬───────┘
                 ▼
        ConversationFSM
        │   (state: IDLE → SELECTING_SPECIALTY → ... → CONFIRMED)
        │
    ┌───┴───────────────────────┐
    ▼                           ▼
AppointmentService         WhatsAppGateway
(emr.Appointment.create)   (send button menu / text)

Celery Beat ──────────────► send_appointment_reminders (every 15 min)
                             mark_no_shows (every 1h)
```

---

## Multi-Tenant Webhook Configuration

Each tenant has their own Evolution API instance and their own webhook URL (their subdomain):
- `https://clinica-abc.vitali.com.br/api/v1/whatsapp/webhook`
- django-tenants middleware routes this to `clinica-abc`'s schema automatically.

When setting up a tenant's WhatsApp connection (QR scan on `/configuracoes/whatsapp`), the app must call Evolution API to set the webhook URL to `https://{tenant_domain}/api/v1/whatsapp/webhook`. This is done programmatically in the settings view, not manually.

**Never use a shared/generic URL** for the webhook — each tenant must have their own.

## Critical: Webhook Must Return 200

Evolution API retries on any non-2xx response. The webhook view MUST:
```python
try:
    dispatch_message(payload)
except Exception as exc:
    logger.critical("Webhook dispatch failed: %s", exc, exc_info=True)
return Response({"status": "ok"}, status=200)  # Always 200
```

## Module Gating

```python
_WHATSAPP_MODULE = ModuleRequiredPermission("whatsapp")
```

Applied to all `apps.whatsapp` views. Webhook endpoint is exempt (must receive from Evolution API without auth checks beyond HMAC).

---

## Data Models (new)

```
WhatsAppContact
  phone: CharField(20, unique=True)
  patient: FK(Patient, null=True, blank=True)
  opt_in: BooleanField(default=False)
  opt_in_at: DateTimeField(null=True)
  opt_out_at: DateTimeField(null=True)
  created_at: DateTimeField(auto_now_add=True)

ConversationSession  ← EPHEMERAL. Deleted after appointment created or after 30min timeout.
  contact: FK(WhatsAppContact)
  state: CharField(choices=FSM_STATES)
  context: TypedDict accessor (see whatsapp/context.py)
    # keys: specialty_id, professional_id, date, slot_start, slot_end,
    #        booking_for_self (bool), other_name, other_cpf (DELETED on session close)
  expires_at: DateTimeField  # now() + 30min, refreshed on each message
  created_at: DateTimeField(auto_now_add=True)
  updated_at: DateTimeField(auto_now=True)

MessageLog  ← PERMANENT audit trail. PII-redacted for LGPD compliance.
  contact: FK(WhatsAppContact)
  direction: CharField(choices=['inbound', 'outbound'])
  content_preview: CharField(200)  # first 200 chars, CPF masked as ***-***-**{last digit}
  message_type: CharField(choices=['text', 'button_reply', 'template'])
  appointment: FK(Appointment, null=True)  # linked after booking
  created_at: DateTimeField(auto_now_add=True)

ScheduledReminder
  appointment: FK(Appointment, unique_together=['appointment', 'reminder_type'])
  reminder_type: CharField(choices=['24h', '2h', 'satisfaction'])
  sent_at: DateTimeField(null=True)
  status: CharField(choices=['pending', 'sent', 'failed', 'responded'], db_index=True)
```

## Frontend: WhatsApp Settings Page States

```
/configuracoes/whatsapp
├── Tab 1: Conexão (admin only)
│   ├── IDLE: QR code displayed + "Escaneie com seu WhatsApp"
│   ├── CONNECTING: LoadingSkeleton + "Aguardando confirmação..."
│   ├── CONNECTED: StatusBadge(success) + phone number + last heartbeat timestamp
│   │              [Reconectar] button (secondary)
│   └── ERROR: StatusBadge(critical) + error message + [Tentar novamente] button
│
└── Tab 2: Conversas (receptionist)
    ├── EMPTY: EmptyState "Nenhuma conversa ainda."
    └── LIST: MessageLog card list (latest first)
              card: patient name | phone | last message preview | timestamp
              click → modal with full MessageLog for that contact
```

## Frontend: Appointment Badge Spec

```
WhatsApp badge on appointment card (read-only status indicator):

Precedence (highest → lowest):
  1. confirmed_via_whatsapp → bg-green-50 text-green-700 "WhatsApp ✓"
  2. reminder_sent (not confirmed) → bg-yellow-50 text-yellow-700 "Lembrete enviado"
  3. opt_in exists but no reminder yet → bg-blue-50 text-blue-700 "WhatsApp"
  4. no WhatsApp number → badge hidden (don't show grey badge, just absence)

Component: StatusBadge (existing DESIGN.md pattern)
Size: text-xs pill, inline after appointment type in card header
Interaction: read-only (click opens conversation history modal if opted-in)
```

---

## Environment Variables (new)

```
WHATSAPP_EVOLUTION_URL=http://evolution-api:8080
WHATSAPP_EVOLUTION_API_KEY=<generated>
WHATSAPP_WEBHOOK_SECRET=<generated>
WHATSAPP_INSTANCE_NAME=vitali
WHATSAPP_CLINIC_PHONE=+5511999999999  # fallback for human handoff
```

## Local Development Note

Evolution API requires a public webhook URL. For local dev:
```bash
# Install ngrok or use localtunnel
ngrok http 8000  # then set webhook URL in Evolution API to https://<tunnel>/api/v1/whatsapp/webhook
```
Or configure Evolution API to post to host.docker.internal:8000 within the Docker network.

## LGPD Opt-in Message Template

The first message sent to any new contact (before any content):

```
Olá! 👋 Sou o assistente virtual da [Clinic Name].

Para enviar mensagens sobre consultas e lembretes, precisamos do seu consentimento conforme a LGPD (Lei 13.709/2018).

✅ *Aceitar* — para receber informações sobre consultas
❌ *Recusar* — para não receber mensagens

Você pode cancelar a qualquer momento enviando *SAIR*.
```

Store `WHATSAPP_CLINIC_NAME` from env or `TenantAIConfig` / clinic profile.

## FSM State Diagram

```
                   ┌─────────────────────────────────────────────┐
                   │              ConversationFSM                │
                   └─────────────────────────────────────────────┘

[any state] ──"sair"/"parar"──────────────────────────────────► OPTED_OUT (terminal)

IDLE ────────────────────── new message ──────────────────────► PENDING_OPTIN
PENDING_OPTIN ──── "aceitar"/intent:optin ───────────────────► SELECTING_SELF_OR_OTHER
PENDING_OPTIN ──── "recusar"/intent:optout ──────────────────► OPTED_OUT

SELECTING_SELF_OR_OTHER ── "para mim" ──────────────────────► SELECTING_SPECIALTY
SELECTING_SELF_OR_OTHER ── "para outra" ────────────────────► CAPTURING_NAME
CAPTURING_NAME ─────────── name received ───────────────────► CAPTURING_CPF
CAPTURING_CPF ──────────── valid CPF ───────────────────────► SELECTING_SPECIALTY
CAPTURING_CPF ──────────── invalid CPF ─────────────────────► CAPTURING_CPF (retry, max 3)

SELECTING_SPECIALTY ─────── specialty chosen ───────────────► SELECTING_PROFESSIONAL
SELECTING_PROFESSIONAL ──── professional chosen ────────────► SELECTING_DATE
SELECTING_DATE ─────────── date chosen ─────────────────────► SELECTING_TIME
SELECTING_TIME ─────────── time chosen ─────────────────────► CONFIRMING
CONFIRMING ─────────────── "confirmar" ─────────────────────► CONFIRMED (appointment created)
CONFIRMING ─────────────── "cancelar" ──────────────────────► IDLE (restart)
CONFIRMING ─────────────── "remarcar" ──────────────────────► SELECTING_DATE

[any scheduling state] ──── 3x unrecognized ────────────────► FALLBACK_HUMAN
[any scheduling state] ──── idle 30min ─────────────────────► IDLE (session expired)

CONFIRMED ──────────────── new message ─────────────────────► SELECTING_SELF_OR_OTHER
```

## Slot Generation Service

`apps/whatsapp/slot_service.py` — `get_available_slots(professional, date_range)`:
- Query `ScheduleConfig` for working days, hours, slot_duration, lunch window
- Generate all slots within working hours (minus lunch break)
- Query existing `Appointment` objects for the date range to subtract booked slots
- Return `{date: [TimeSlot(start, end), ...]}` for the next 7 working days
- ~100 LOC, needs unit tests with appointment collision scenarios

---

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|---------|
| 1 | CEO/Premises | Add keyword intent detection to FSM | Taste → User confirmed | P1 Completeness | Freeform "quero marcar" is the dominant patient input pattern in Brazil; pure menu-driven will hit fallback constantly | Menu-only (Completeness 7/10) |
| 2 | CEO/Premises | Add "booking for someone else" FSM state | Taste → User confirmed | P1 Completeness | Shared phones are real in Brazilian clinic context (spouse, parent-child); one extra state catches the case | One-phone=one-patient (Completeness 7/10) |
| 3 | CEO/0C-bis | DB-backed ConversationSession (not Redis) | Mechanical | P3 Pragmatic, P5 Explicit | MVP scale (dozens concurrent), DB latency irrelevant; admin visibility > perf at this scale | Redis-backed (session loss on restart, no admin view) |
| 4 | CEO/SELECTIVE | Post-visit satisfaction survey | Mechanical (in blast radius, ~2h) | P2 Boil lakes | Same Celery Beat + WhatsApp task infrastructure, trivially adds 1 outbound message per completed appointment | Deferred |
| 5 | CEO/SELECTIVE | Conversation history view (receptionist) | Mechanical (in blast radius, ~3h) | P2 Boil lakes | Receptionist page to see message thread per patient, same module, needed for support debugging | Deferred |
| 6 | CEO/SELECTIVE | Prescription notifications → TODOS | Mechanical (out of blast radius) | P3 Pragmatic | Crosses pharmacy module boundary, adds cross-module dependency mid-sprint | — |
| 7 | CEO/SELECTIVE | Recurring follow-up reminders → TODOS | Mechanical (out of blast radius, ~1d) | P3 Pragmatic | Requires appointment history analysis + new query logic, scope too large for this sprint | — |
| 8 | CEO/SELECTIVE | Bulk broadcast → TODOS | Mechanical (out of blast radius) | P3 Pragmatic | New UI surface + significant backend, separate feature not in E-009 scope | — |
| 9 | CEO/Section1 | Webhook must always return HTTP 200 | Mechanical | P5 Explicit | Evolution API retries on non-2xx; must catch all exceptions at view layer | Propagating 500 to Evolution API |
| 10 | CEO/Section3 | Delete ConversationSession after appointment created (CPF is PII) | Mechanical | P1 Completeness | CPF stored in context JSONField must not persist after scheduling completes; LGPD compliance | Keeping session for history |
| 11 | CEO/Section3 | Per-contact rate limiting in FSM (max 20/min) | Mechanical | P1 Security | Prevent flood attacks via webhook; simple Django cache counter, cost ~5 LOC | No rate limiting |
| 12 | CEO/Section4 | Atomic slot reservation at CONFIRMING step | Mechanical | P1 Completeness | Race condition: two patients pick same slot, both confirm. Re-check availability inside transaction before Appointment.save() | Trust first-seen |
| 13 | CEO/Section4 | ConversationSession.select_for_update() on processing | Mechanical | P1 Completeness | Concurrent messages (patient double-taps) can corrupt FSM state; row-level lock prevents this | Risk of duplicate state transitions |
| 14 | CEO/Section4 | Reminder idempotency guard (ScheduledReminder.sent_at check) | Mechanical | P1 Completeness | Celery task may run twice (retry + original); must check sent_at is None before sending | Double reminders to patients |
| 15 | CEO/Dual Voice | Add hard success metrics + no-show baseline | Mechanical | P2 Boil lakes | Both models flagged absent success metrics; baseline measurement before ship is a 30min task | Ship without measurement |
| 16 | CEO/Dual Voice | Scope width (Codex concern) → hold scope | Taste | P3 Pragmatic | Codex says bundle too wide; auto-held because stories are interdependent roadmap items | — |
| 17 | CEO/Dual Voice | ScheduledReminder select_for_update in Celery task | Mechanical | P1 Completeness | Race: two Celery workers process same reminder simultaneously; row lock prevents double send | Risk of duplicate reminders sent |
| 18 | Design/Phase2 | QR page 4-state spec (IDLE/CONNECTING/CONNECTED/ERROR) | Mechanical | P1 Completeness | Both models flagged absent states; implementer would guess, producing inconsistent UX | No state spec |
| 19 | Design/Phase2 | Badge precedence: confirmed > sent > opted-in > absent (no grey badge) | Mechanical | P5 Explicit | Both models flagged ambiguity; semantic token mapping prevents "red for status" violations | Ambiguous color choice |
| 20 | Design/Phase2 | MessageLog model (permanent, PII-redacted) separate from ConversationSession | Mechanical | P1 Completeness + LGPD | Without MessageLog, conversation history view shows nothing after session deletion | Keep session long-term |
| 21 | Design/Phase2 | Settings page: Tab 1 (admin: QR + status) + Tab 2 (receptionist: conversations) | Mechanical | P5 Explicit | One page two masters; tab split matches existing /configuracoes pattern | Mix on single page |
| 22 | Eng/Phase3 | TypedDict accessor for ConversationSession.context (whatsapp/context.py) | Mechanical | P5 Explicit | JSONField is a string dict at runtime; typo `ctx['speciality_id']` vs `ctx['specialty_id']` is an invisible bug that surfaces only at booking-time. TypedDict + get_context() accessor catches it at dev time. | Plain dict access |
| 23 | Eng/Phase3 | Store `other_patient_id` FK in context, not raw CPF string | Mechanical | P1 Security + LGPD | CPF in JSONField persists in DB snapshots, backups, admin history. After patient is matched/created, swap raw CPF for patient PK immediately. Delete session after booking. | Keep CPF string in context |
| 24 | Eng/Phase3 | requests>=2.32 added to backend/requirements/base.txt | Mechanical | P5 Explicit | Not currently installed. EvolutionAPIGateway uses requests.post(). Missing dep = ImportError on boot. | — |
| 25 | Eng/Phase3 | Multi-tenant webhook: programmatically set webhook URL during QR setup | Mechanical | P5 Explicit | Tenant subdomain must be the webhook URL — manual config per-tenant is an ops error waiting to happen. The settings view calls Evolution API to register it. | Manual config per tenant |
| 26 | Eng/Phase3 | N+1 guard: send_appointment_reminders must use select_related('contact', 'appointment__patient', 'appointment__professional') | Mechanical | P1 Completeness | Without select_related, each reminder row triggers 3+ queries. At 100 appointments/query window that's 300+ queries. One annotated queryset fixes it. | Per-row query |
| 27 | Eng/Phase3 | MessageLog conversation history view uses select_related + contact filter; no prefetch of ConversationSession | Mechanical | P3 Pragmatic | ConversationSession is ephemeral; history view reads MessageLog only. select_related('contact', 'appointment') on the queryset, paginated to 50. | — |

---

## Engineering Review (Phase 3)

### Section 1 — Architecture Dependency Graph

```
apps/whatsapp/
├── gateway.py          (WhatsAppGateway ABC + EvolutionAPIGateway)
│   └── depends: requests>=2.32, django.conf.settings
├── models.py           (WhatsAppContact, ConversationSession, MessageLog, ScheduledReminder)
│   └── depends: apps.emr.models (Patient, Appointment), django_tenants schema isolation
├── context.py          (ConversationContext TypedDict + get_context() accessor)
│   └── no deps
├── fsm.py              (ConversationFSM, keyword intent detection)
│   └── depends: gateway.py, context.py, slot_service.py, apps.emr.Appointment
├── slot_service.py     (get_available_slots)
│   └── depends: apps.emr.models (ScheduleConfig, Appointment)
├── views.py            (WebhookView, WhatsAppContactViewSet, MessageLogViewSet, HealthView)
│   └── depends: fsm.py, gateway.py, apps.core.permissions.ModuleRequiredPermission
├── tasks.py            (send_appointment_reminders, mark_no_shows, send_satisfaction_surveys,
│                        cleanup_expired_sessions)
│   └── depends: models.py, gateway.py, celery
├── serializers.py      (WhatsAppContactSerializer, MessageLogSerializer)
│   └── depends: models.py, apps.emr.serializers
└── migrations/
    ├── 0001_initial.py         (all 4 models)
    └── 0002_celery_beat_tasks.py  (data migration: register 4 Celery Beat tasks)

External:
  Evolution API (Docker container, atendai/evolution-api:latest)
    ← webhook POST → views.WebhookView
    ← REST calls → gateway.EvolutionAPIGateway (requests.post)

Django-tenants:
  All models are tenant-scoped (no public schema models)
  Webhook URL must include tenant subdomain — set programmatically on QR scan
```

### Section 2 — Code Quality Constraints

**gateway.py**
- `EvolutionAPIGateway` must have `timeout=10` on all requests.post() calls. No hanging webhook threads.
- `send_if_opted_in(contact, ...)`: check `contact.opt_in` before calling `send_text`. Raise `OptOutError` (custom exc) if opted out — caller handles gracefully.
- All gateway methods log request+response at DEBUG level (not INFO — avoids flooding logs with message content).

**fsm.py**
- `ConversationFSM.process(message)` is the only entry point. Returns `(new_state, outbound_messages: list[str])`.
- Keyword intent detection: normalize input (`.strip().lower()`, remove accents via `unicodedata.normalize`) then check against INTENT_MAP dict. ~30 LOC.
- Max 3 unrecognized inputs before FALLBACK_HUMAN — tracked in `ConversationSession.context['mismatches']`.
- `select_for_update()` on ConversationSession at the start of `process()` — prevents concurrent double-tap corruption.
- Slot reservation at CONFIRMING: open `transaction.atomic()`, re-check slot availability with `select_for_update()` on overlapping Appointment rows, then save. If slot taken: send "Desculpe, esse horário acabou de ser reservado. Escolha outro:" → back to SELECTING_TIME.

**tasks.py**
- `send_appointment_reminders`: `ScheduledReminder.objects.filter(status='pending', appointment__datetime__lte=cutoff).select_for_update(skip_locked=True).select_related('appointment__patient', 'appointment__professional', 'contact')` — skip_locked avoids deadlock with concurrent workers.
- `cleanup_expired_sessions`: `ConversationSession.objects.filter(expires_at__lt=now()).delete()` — runs every 15 min.
- All tasks decorated `@shared_task(bind=True, max_retries=3, default_retry_delay=60)`.

**migrations/0002_celery_beat_tasks.py**
- Follow pattern from `apps/ai/migrations/0004_schedule_celery_beat_tasks.py` (existing).
- Four tasks: `send_appointment_reminders` (every 15min), `mark_no_shows` (hourly), `send_satisfaction_surveys` (hourly), `cleanup_expired_sessions` (every 15min).

### Section 3 — Test Coverage Diagram

```
apps/whatsapp/tests/
├── test_gateway.py
│   ├── EvolutionAPIGatewayTests
│   │   ├── test_send_text_posts_to_evolution_api              [mock requests]
│   │   ├── test_send_button_menu_formats_payload_correctly    [mock requests]
│   │   ├── test_timeout_10s_enforced                          [mock requests.post side_effect=Timeout]
│   │   └── test_send_if_opted_out_raises_optout_error         [unit]
│   └── WebhookSignatureTests
│       ├── test_valid_hmac_returns_200                        [APIClient]
│       ├── test_invalid_hmac_still_returns_200_but_drops      [APIClient] ← Decision #9
│       └── test_missing_signature_header_returns_200_drops    [APIClient]
│
├── test_fsm.py
│   ├── ConversationFSMTests
│   │   ├── test_idle_to_pending_optin_on_first_message        [unit]
│   │   ├── test_optin_accepted_advances_to_self_or_other      [unit]
│   │   ├── test_optin_refused_goes_to_opted_out               [unit]
│   │   ├── test_sair_from_any_state_goes_to_opted_out         [parametrize all states]
│   │   ├── test_keyword_intent_agendar_triggers_scheduling    [unit]
│   │   ├── test_keyword_intent_cancelar_triggers_cancel       [unit]
│   │   ├── test_keyword_accent_normalized_matches             [unit: "agéndar" → agendar]
│   │   ├── test_3x_unrecognized_goes_to_fallback_human        [unit]
│   │   ├── test_full_booking_flow_self                        [integration: IDLE→CONFIRMED]
│   │   ├── test_full_booking_flow_for_other_person            [integration: captures name+CPF]
│   │   ├── test_slot_collision_at_confirming_retries_to_time  [integration + transaction]
│   │   ├── test_remarcar_at_confirming_returns_to_date        [unit]
│   │   └── test_expired_session_resets_to_idle                [unit: expires_at in past]
│   └── ConversationSessionLockingTests
│       ├── test_concurrent_messages_do_not_corrupt_state      [threading: 2 threads, same session]
│       └── test_select_for_update_used_in_process             [mock: verify queryset has .select_for_update()]
│
├── test_slot_service.py
│   ├── SlotServiceTests
│   │   ├── test_returns_slots_within_working_hours            [unit: ScheduleConfig fixture]
│   │   ├── test_excludes_booked_appointments                  [unit]
│   │   ├── test_excludes_lunch_break                          [unit]
│   │   ├── test_excludes_non_working_days                     [unit]
│   │   └── test_returns_7_days_ahead_maximum                  [unit]
│
├── test_views.py
│   ├── WebhookTenantRoutingTests
│   │   ├── test_webhook_routes_to_correct_tenant_schema       [TenantTestCase, two tenants]
│   │   └── test_webhook_from_wrong_tenant_drops_silently      [TenantTestCase]
│   └── MessageLogViewSetTests
│       ├── test_receptionist_can_list_logs_for_their_tenant   [TenantTestCase]
│       └── test_receptionist_cannot_see_other_tenant_logs     [TenantTestCase]
│
├── test_tasks.py
│   ├── ReminderIdempotencyConcurrencyTests
│   │   ├── test_reminder_not_sent_twice_on_concurrent_workers [threading: skip_locked]
│   │   ├── test_status_pending_to_sent_transition             [unit]
│   │   └── test_failed_reminder_increments_retry_count        [unit]
│   ├── NoShowTrackingTests
│   │   ├── test_appointment_past_without_confirmation_marked_no_show  [unit]
│   │   └── test_appointment_confirmed_via_whatsapp_not_marked_no_show [unit]
│   └── SatisfactionSurveyTests
│       ├── test_survey_sent_2h_after_completed_status         [unit]
│       ├── test_survey_not_sent_if_no_optin                   [unit]
│       └── test_survey_not_sent_twice                         [unit: ScheduledReminder deduplication]
│
├── test_lgpd.py
│   ├── CPFRedactionAndSessionPurgeTests
│   │   ├── test_cpf_in_context_replaced_by_patient_id_after_match  [integration]
│   │   ├── test_session_deleted_after_appointment_created           [integration]
│   │   ├── test_messagelog_cpf_masked_in_content_preview            [unit]
│   │   └── test_cleanup_expired_sessions_task_deletes_old_sessions  [unit]
│   └── PerContactRateLimitTests
│       ├── test_21st_message_in_1min_returns_200_but_drops    [APIClient + cache mock]
│       └── test_rate_limit_resets_after_window                [APIClient + cache mock]
│
└── test_isolation.py
    └── CrossTenantSamePhoneIsolationTests
        ├── test_phone_in_tenant_a_invisible_to_tenant_b       [TenantTestCase: two schemas]
        └── test_optin_in_tenant_a_does_not_affect_tenant_b    [TenantTestCase]

Performance regression tests (separate, CI-gated):
└── test_query_counts.py
    └── ReminderQueryCountTests
        ├── test_send_reminders_for_100_appointments_uses_le_5_queries  [assertNumQueries(5)]
        └── test_messagelog_list_50_items_uses_le_3_queries             [assertNumQueries(3)]
```

**Total test classes: 12 | Total test methods: ~45**

**Coverage requirements:**
- `gateway.py`: 100% (safety-critical: message sending, HMAC validation)
- `fsm.py`: 100% (all state transitions + keyword intent map)
- `slot_service.py`: 100% (collision detection correctness)
- `tasks.py`: 90%+ (retry paths tested by concurrency tests)
- `views.py`: 85%+ (webhook always-200 path fully covered)
- `lgpd.py` paths: 100% (regulatory requirement)

### Section 4 — Performance

**Webhook processing latency budget:**
- HMAC validation: <1ms (pure Python crypto)
- ConversationSession DB lookup + lock: <5ms (indexed on contact_id)
- FSM state transition: <2ms (no I/O in state logic itself)
- Gateway send_text() to Evolution API: up to 500ms (async is overkill at current scale; sync is fine)
- **Total webhook round-trip: target <600ms P95**

**Celery task sizing:**
- `send_appointment_reminders` window: appointments in next 25min (runs every 15min, 10min buffer)
- Expected volume: pilot clinic = ~20 appointments/day = ~2 reminders due per 15min window
- At 100 appointments/day: still <10 per window. select_related covers the N+1 completely.
- Task SLA: complete within 60 seconds, timeout=120s

**DB index requirements (new):**
```sql
-- ConversationSession
CREATE INDEX whatsapp_conversationsession_contact_id ON whatsapp_conversationsession(contact_id);
CREATE INDEX whatsapp_conversationsession_expires_at ON whatsapp_conversationsession(expires_at);
-- ScheduledReminder
CREATE INDEX whatsapp_scheduledreminder_status ON whatsapp_scheduledreminder(status);
CREATE INDEX whatsapp_scheduledreminder_appointment_id ON whatsapp_scheduledreminder(appointment_id);
-- WhatsAppContact
-- phone is already unique (implicit index)
```

**Migration strategy:**
- All new tables. Zero ALTER TABLE on existing models except:
  - `emr.Appointment`: ADD COLUMN `satisfaction_rating INTEGER NULL` — safe, nullable, no backfill
- No downtime risk. Run migrations before deploying new code (migration-first deploy).
- Rollback: `python manage.py migrate whatsapp zero` drops all 4 new tables cleanly.

---

## Pre-flight Checklist (Before First Line of Code)

- [ ] Measure current no-show rate (baseline metric for S-034 success criteria)
- [ ] Add `requests>=2.32` to `backend/requirements/base.txt`
- [ ] Add Evolution API to `docker-compose.yml`
- [ ] Add 5 env vars to `.env.example` (WHATSAPP_*)
- [ ] Rebuild containers: `make down && make up` (prior sprint pip-installed anthropic/jinja2 live — will vanish without rebuild)
- [ ] Confirm `apps.whatsapp` is in `INSTALLED_APPS` and `ALLOWED_MODULE_KEYS`

---

## TODOs (Deferred — Not In Sprint 12)

```markdown
<!-- TODO: Prescription ready notifications via WhatsApp
     Crosses pharmacy module boundary. Needs WhatsAppGateway available to pharmacy app.
     Blocked on: clear cross-module event bus design.
     Complexity estimate: 1 day. -->

<!-- TODO: Recurring follow-up reminders
     Post-surgery / chronic condition recurring reminders.
     Requires: appointment history analysis, frequency config per specialty.
     Complexity estimate: 2 days. -->

<!-- TODO: Bulk broadcast to opted-in patients
     New UI surface in /marketing or /comunicacao section.
     Requires: template approval flow, send-rate throttling, unsubscribe tracking.
     Complexity estimate: 1 week (separate epic). -->
```

