<!-- /autoplan restore point: /home/rcosta00/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260406-173853.md -->
<!-- autoplan: tropeks-Vitali / master / eb34bb4 / 2026-04-06 -->
# Sprint 16: Clinical UI Layer + Phase 2 AI (v1.1.0)

**Theme:** Complete the v1.0.0 UI surface, give clinic owners operational visibility, and kick off Phase 2 AI with voice dictation.

**Version target:** v1.1.0

**Stories:** S-067, S-068, S-069

**Total points:** 34 (13 + 8 + 13)

**Pre-req state (what v1.0.0 gives us):**
- Sprint 15 backend complete: `TOTPDevice`, `AISafetyAlert`, `AICIDSuggestion`, `WaitlistEntry`, `PrescriptionPDFGenerator`
- `LLMGateway` + `ClaudeGateway` (Sprint 9)
- Celery + Redis (Sprint 13)
- WhatsApp gateway (Sprint 12)
- `DESIGN.md` Vitali design system in place
- `AIDPAStatus` model (Sprint 15 migration `core.0009`)

---

## S-067: Sprint 15 Frontend Implementation

**Goal:** Build all React/Next.js UI components for the 5 Sprint 15 backend stories that shipped without frontend: MFA, prescription safety, CID10 AI, prescription PDF, and waitlist.

**Acceptance Criteria:**
- Staff user enrolls TOTP from `/profile/security` page: scans QR code, enters confirmation code, downloads 8 backup codes as TXT.
- After login with `mfa_required: true` in response, redirected to `/auth/mfa` to enter 6-digit TOTP (auto-submit on 6th digit).
- Prescription builder item row shows safety badge: spinner → green "Seguro" / amber ⚠ / red 🚫 (within 5s).
- Doctor can click amber/red badge → `SafetyAlertModal` shows alert details + acknowledge input (required if contraindication).
- Encounter edit form "Hipótese diagnóstica" textarea shows CID10 suggestion panel after 1.5s debounce (min 20 chars): 3 chips with code + description + confidence; click to fill "CID-10 principal".
- Prescription detail page "Imprimir Receita" button → opens PDF in new tab (signed only; unsigned shows disabled button).
- Receptionist `/appointments/waitlist` page: lists active entries with status badges (waiting / notified / expired), can cancel entry.
- Unavailable booking slot shows "Entrar na fila de espera" secondary button.

**Backend (already done — Sprint 15):**
- All 8 endpoints: `/auth/mfa/setup/`, `/auth/mfa/verify/`, `/auth/mfa/login/`, `/auth/mfa/disable/`, safety-check, cid10-suggest, cid10-accept, prescriptions PDF, waitlist CRUD

**Frontend:**
- `app/(dashboard)/profile/security/page.tsx` — MFA settings: status badge, "Configurar Autenticação de Dois Fatores" button, enrollment flow (QR display → code input → backup codes download)
- `app/auth/mfa/page.tsx` — 6-digit TOTP input (OTP-style, auto-submit on 6th digit), "Usar código de backup" link
- `components/prescriptions/SafetyBadge.tsx` — polling `GET /safety-check/` every 2s for 10s; settles to result badge
- `components/prescriptions/SafetyAlertModal.tsx` — drawer/sheet with alert list, acknowledge form with validation (min 10 chars for contraindications)
- `components/emr/CID10Suggest.tsx` — debounced textarea wrapper; suggestion panel with 3 `Button` chips; integrates with `POST /cid10-suggest/` and `POST /cid10-accept/`
- `app/(dashboard)/appointments/waitlist/page.tsx` — paginated table with patient name, professional, dates, status badge, cancel action
- Prescription detail: add "Imprimir Receita" primary button that calls `GET /prescriptions/{id}/pdf/` and triggers download

**Tests (frontend — Vitest/Playwright):**
- MFA setup renders QR image from API response
- Safety badge transitions from spinner → badge on API response
- CID10 suggestion panel appears after debounce delay, not before
- "Imprimir Receita" disabled for unsigned prescription

**Story Points:** 13

---

## S-068: Clinic Operations Dashboard

**Goal:** Pilot clinic owners see their operations health at a glance. This was explicitly deferred from Sprint 15 autoplan as the #1 priority for pilot retention ("pilot churn week 3" risk from CEO subagent).

**Acceptance Criteria:**
- `GET /api/v1/analytics/clinic-ops/?period=today|week|month` returns:
  - `appointments`: total, confirmed, no_show, completed, fill_rate (%)
  - `revenue`: total TISS guide value (status submitted/paid), period comparison
  - `wait_time_avg_min`: avg minutes from check-in to consultation start
  - `sparkline`: last 7 days daily appointment counts
  - `top_professionals`: top 3 by appointment count in period
- `/dashboard` landing page (replaces stub) shows: 5 KPI cards, 7-day sparkline, top professionals table.
- Works with zero data (all KPIs return 0, empty states with helpful copy).
- Date range filter: today / this week / this month.
- Response time < 200ms (query uses existing indexes; add missing indexes if needed).

**Backend:**
- `apps/analytics/views_clinic_ops.py`: `ClinicOpsView` (GET, IsAuthenticated)
  - Aggregates `Appointment`, `TISSGuide`, `Schedule` models
  - `fill_rate = confirmed_count / available_slots_count` (available slots from professional `Schedule` + `TimeSlot` config)
  - `no_show_rate = no_show_count / (confirmed_count or 1)`
  - `wait_time_avg`: avg of `appointment.started_at - appointment.arrived_at` (both non-null required)
  - Period filter: `today` = `appointment_date = today`, `week` = current ISO week, `month` = current month
- `apps/analytics/urls.py`: add `path('clinic-ops/', ClinicOpsView.as_view(), ...)`
- No new models, no new migrations — pure aggregation on existing data

**Frontend:**
- `app/(dashboard)/page.tsx` — full ops dashboard replacing stub homepage
- `components/analytics/KPICard.tsx` — reusable: metric value + label + trend indicator (↑ ↓ →) + period comparison
- `components/analytics/Sparkline.tsx` — lightweight 7-day bar sparkline (recharts `BarChart` or inline SVG)
- `components/analytics/TopProfessionalsTable.tsx` — compact ranked table

**Tests:**
- Zero appointments → `fill_rate=0`, `wait_time_avg_min=null`, `revenue=0`
- Period `week` returns only current-week appointments
- `no_show_rate` formula correct (denominator never 0)
- `top_professionals` capped at 3 entries

**Story Points:** 8

---

## S-069: AI Clinical Scribe (Voice → SOAP Notes)

**Goal:** Doctor clicks "Iniciar Ditado" in encounter, speaks clinical findings, and AI generates a structured SOAP note. Cuts documentation time from ~5 min/encounter to < 30 seconds. Phase 2 AI kickoff.

Feature flag: `ai_scribe` (default OFF — requires DPA with Anthropic/data processor agreement per LGPD Art. 11).

**Acceptance Criteria:**
- In encounter detail, "Iniciar Ditado" button starts Web Speech API (`SpeechRecognition`) recording (Chrome/Edge only; other browsers show graceful fallback to plain text textarea).
- After doctor stops speaking, transcription is sent to `POST /api/v1/emr/encounters/{id}/scribe/`.
- API returns SOAP structure: `{s: "...", o: "...", a: "...", p: "..."}`.
- Doctor can edit all 4 SOAP fields before saving.
- "Salvar como Evolução" button creates `ClinicalNote` linked to the encounter.
- Feature flag `ai_scribe=False` → button hidden.
- `AIDPAStatus.dpa_signed_date` null → 403 `{"dpa_required": true}` with link to sign DPA.
- `AIScribeSession` model tracks raw transcription, generated SOAP, and whether accepted.
- LLM: Claude Sonnet 4.6 (better SOAP coherence than Haiku).
- Empty / < 10 chars transcription → 400 `{"error": "Texto muito curto para gerar evolução."}`.

**Backend:**
- `AIScribeSession` model (`apps/emr/`):
  - UUID PK, `encounter FK`, `raw_transcription TextField`, `soap_note JSONField` (`{s, o, a, p}`), `accepted BooleanField default=False`, `accepted_note FK ClinicalNote null=True`, `created_at`
- `apps/emr/services/clinical_scribe.py`:
  - `ClinicalScribe.generate_soap(transcription: str, encounter: Encounter) → SOAPNote`
  - Prompt: Portuguese medical context; structured JSON output `{s, o, a, p}` (Subjetivo = patient complaint, Objetivo = exam findings, Avaliação = assessment/diagnosis, Plano = treatment plan)
  - Reuses `ClaudeGateway.complete()` (Sprint 9)
  - Feature flag check: `get_tenant_ai_config().ai_scribe`
  - DPA check: `AIDPAStatus.objects.filter(tenant=...).first().dpa_signed_date is not None`
  - No caching (voice transcriptions are unique)
- `POST /api/v1/emr/encounters/{id}/scribe/` — creates `AIScribeSession`, calls `ClinicalScribe.generate_soap()`, returns `{session_id, soap: {s,o,a,p}}`
- `POST /api/v1/emr/encounters/{id}/scribe/{session_id}/accept/` — creates `ClinicalNote` from SOAP, marks `session.accepted=True`, returns `{note_id}`
- Migration: `apps/emr/migrations/0013_aiscribesession.py`
- URL registrations in `apps/emr/urls.py`

**Frontend:**
- `components/emr/ScribeButton.tsx` — Web Speech API wrapper; states: idle / recording / processing / error
- `components/emr/SOAPEditor.tsx` — 4-panel editable form (Subjetivo / Objetivo / Avaliação / Plano) pre-filled from AI; "Salvar como Evolução" submits to accept endpoint
- Encounter detail: add Scribe button above clinical notes section; hide if `ai_scribe` flag off or DPA unsigned
- LGPD notice: first use shows inline banner "Esta funcionalidade envia transcrições de voz ao Claude (Anthropic). Consentimento já coletado no DPA do tenant."

**Tests:**
- Feature flag OFF → `POST /scribe/` returns 403
- DPA unsigned → returns 403 with `{"dpa_required": true}`
- Valid transcription (> 10 chars) → returns SOAP with all 4 fields non-empty strings
- Accept endpoint creates `ClinicalNote` with correct `encounter`, `note_type="soap"`
- Empty transcription → 400
- `AIScribeSession.accepted=True` after accept call

**Story Points:** 13

---

## Technical Scope

### New models
- `AIScribeSession` (tenant schema, `apps/emr/`)

### New migrations
- `apps/emr/migrations/0013_aiscribesession.py`

### New endpoints
- `GET /api/v1/analytics/clinic-ops/`
- `POST /api/v1/emr/encounters/{id}/scribe/`
- `POST /api/v1/emr/encounters/{id}/scribe/{session_id}/accept/`

### New feature flags (auto-seeded)
- `ai_scribe` — default OFF (DPA required before activation)

### New dependencies
None (Web Speech API is browser-native; LLM reuses ClaudeGateway)

---

## Acceptance Criteria — Sprint-Level

All 3 stories pass at demo:
1. Staff user completes full MFA enrollment flow via UI: QR scan → confirm code → backup codes TXT downloaded. ✓
2. Doctor opens prescription builder, adds drug with known patient allergy → safety badge transitions from spinner to red 🚫 within 5s → clicks badge → modal shows alert + acknowledge form.
3. Doctor types "dor no peito com irradiação para braço esquerdo" in encounter diagnosis field → 3 CID10 chips appear → clicks "I25.1" → CID-10 principal field filled.
4. Signed prescription detail page → "Imprimir Receita" → PDF opens with SHA-256 hash in footer.
5. Receptionist views `/appointments/waitlist` → sees 2 waiting entries → cancels entry → status updates to "cancelado".
6. Clinic owner opens `/dashboard` → sees today's appointment count, fill rate, revenue, 7-day sparkline.
7. Doctor clicks "Iniciar Ditado" in encounter → speaks 30 seconds → SOAP note appears with 4 filled sections → saves as clinical note.

---

## Dependencies & Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Web Speech API unsupported (Firefox, Safari mobile) | High | Fallback: plain text textarea; scribe endpoint accepts typed text too |
| AI Scribe DPA not signed at demo time | Med | Feature flag OFF by default; build infrastructure, demo with DPA pre-signed in seed data |
| Sprint 15 backend integration gaps discovered during frontend work | Med | 355 tests already green; write integration tests as frontend is built |
| Dashboard fill rate needs Schedule capacity data (not always configured) | Med | Fallback: if no Schedule configured, fill_rate=null + "Configure horários" CTA |
| Claude Sonnet 4.6 context length for long voice transcriptions | Low | Max transcription: 5 min ≈ 800 words; well within 200k token context |

---

## Story Point Total: 34
**Estimated CC+gstack time:** ~80 min implementation

---

# AUTOPLAN — Phase 1: CEO Review

**Mode:** SELECTIVE EXPANSION | **Branch:** master | **Date:** 2026-04-06
**Dual voices:** [subagent-only] — Codex not available in this environment

---

## PRE-REVIEW SYSTEM AUDIT

**Existing analytics surface (apps/analytics/views.py):**
- `OverviewView` — today + MTD: `appointments_total`, `appointments_completed`, `appointments_waiting`, `appointments_cancelled`, `new_patients`, `encounters_open`, `encounters_signed`, `cancellation_rate`
- `AppointmentsByDayView` — configurable-day sparkline (default 30d, zero-filled, continuous)
- `TopProfessionalsView` — top N by completed appointments, current month
- `AppointmentsByStatusView` — current month, grouped by status
- `WaitingTimeView` — returns placeholder zeros (Appointment lacks `arrived_at`/`started_at` timestamps)
- **All use `_BILLING_MODULE` permission** — restricts to clients with billing module active

**Critical finding:** S-068 proposes building a new `ClinicOpsView` + `views_clinic_ops.py` that aggregates the same 3 models with nearly identical logic to endpoints that already exist. This is a premise failure — the plan assumes "no clinic ops data exists" without checking.

---

## 0A. Premise Challenge

| Premise | Status | Finding |
|---------|--------|---------|
| P1: Sprint 15 backend is complete and integrated | ✅ CONFIRMED | 355 tests passing; models, migrations, endpoints all in place |
| P2: Clinic ops dashboard requires a new endpoint (`/clinic-ops/`) | ❌ FALSE | `OverviewView` + `AppointmentsByDayView` + `TopProfessionalsView` already cover ~80% of S-068's data requirements; the new endpoint duplicates query logic and creates two sources of truth |
| P3: `fill_rate` is computable for pilot clinics | ⚠️ RISKY | Requires `Schedule` + `TimeSlot` config per professional; new clinics won't have this configured; dashboard will show null fill rate for week-3 pilots — the exact cohort S-068 was designed to retain |
| P4: `wait_time_avg` is computable from existing data | ❌ FALSE | Requires `Appointment.arrived_at` and `Appointment.started_at` timestamps; neither field exists on the model; `WaitingTimeView` already returns placeholder zeros for this reason |
| P5: Web Speech API covers clinic devices | ⚠️ RISKY | Chrome/Edge only; Brazilian clinics frequently run Android + Firefox or older iOS Safari; the fallback is described but underspecified — "plain textarea" loses the voice UX entirely |
| P6: DPA enforcement is sufficient for S-069 | ⚠️ WEAK | `AIDPAStatus.dpa_signed_date is not None` check is trivially bypassable by any admin inserting a row; there is no DPA signing flow in the product; compliance enforcement relies on seed data for the demo |
| P7: Frontend-only sprint is acceptable (S-067 = 13pts catch-up) | ⚠️ TECH DEBT SIGNAL | Shipping backend without frontend for an entire sprint doubles WIP cycle time; this sprint exists entirely because Sprint 15 broke definition-of-done; pattern risk if not addressed |

**Challenged premises: P2, P4 (false). P3, P5, P6 (risky). P7 (process signal).**

---

## 0B. Existing Code Leverage Map

| S-068 Sub-problem | Existing Code | Gap |
|-------------------|---------------|-----|
| Today's appointment KPIs | `OverviewView` — already returns total, completed, waiting, cancelled | Permission: `_BILLING_MODULE` too restrictive; needs `IsAuthenticated` for clinic owners |
| 7-day sparkline | `AppointmentsByDayView?days=7` — already returns zero-filled daily counts | Same permission issue |
| Top professionals | `TopProfessionalsView` | Same permission issue |
| Period filter (today/week/month) | Not in existing views — today/MTD only in `OverviewView` | Medium work: add `?period=` param to `OverviewView` |
| Revenue (TISS guides) | `TISSGuide` aggregation exists in billing views; not surfaced in analytics | Small: add revenue line to `OverviewView` |
| Fill rate | No equivalent | Requires `Schedule`/`TimeSlot` config — BLOCKED for most pilots |
| Wait time avg | `WaitingTimeView` — placeholder zeros | BLOCKED: `arrived_at`/`started_at` don't exist on Appointment |
| KPI cards frontend | None | New: `KPICard.tsx`, `Sparkline.tsx`, `TopProfessionalsTable.tsx` |

**Bottom line:** S-068 backend work is 2-3 hours of permission cleanup + query extension on existing views, not a new `views_clinic_ops.py`. Building new means two sources of truth.

---

## 0C. Dream State Mapping

```
CURRENT STATE
├── Sprint 15 backend: MFA, safety checks, CID10, PDFs, waitlist (backend only)
├── Analytics: 6 endpoints, all behind _BILLING_MODULE permission
├── /dashboard: stub homepage (empty)
└── AI: CID10 suggester only (Phase 1)

THIS PLAN (Sprint 16, v1.1.0)
├── S-067: All Sprint 15 features become usable via UI (13pts catch-up)
├── S-068: /dashboard shows clinic KPIs — appointments, revenue, sparkline, top doctors
└── S-069: Voice dictation → SOAP notes (feature-flagged, DPA-gated)

12-MONTH IDEAL (v2.0)
├── Full EMR workflow: zero paper, zero phone calls for booking/prescriptions
├── AI Scribe trusted by doctors — used in >70% of encounters, DPA signed at onboarding
├── Dashboard drives daily clinical decisions, not just "nice to have" metrics
├── Fill rate visible because Schedule is configured for all active professionals
├── Multi-browser voice OR server-side transcription (Whisper) for 100% device coverage
└── Definition of Done enforced: no more "backend-only" sprints
```

**Delta from this plan to 12-month ideal:**
- Fill rate metric requires `Schedule` config rollout (operationally, not engineering)
- Wait time tracking requires `arrived_at`/`started_at` — likely Sprint 17 when digital check-in exists
- Server-side transcription (Whisper) not in scope but needed for non-Chrome clinics
- DPA signing UI not in scope — compliance gap before GA

---

## 0C-bis. Implementation Alternatives

| Approach | Description | Effort | Risk | Completeness |
|----------|-------------|--------|------|--------------|
| **A (Plan as written)** | Build new `ClinicOpsView` + `views_clinic_ops.py`; duplicate aggregation logic | 4h backend + 8h frontend | Medium (two sources of truth, divergence risk) | 6/10 (fill_rate and wait_time broken at launch) |
| **B (Leverage existing — RECOMMENDED)** | Remove `_BILLING_MODULE` from 3 existing analytics views, add `?period=` to `OverviewView`, add revenue line, wire frontend to existing endpoints | 2h backend + 7h frontend | Low (no new query logic) | 8/10 (fill_rate deferred cleanly, wait_time deferred cleanly) |
| **C (Minimal dashboard)** | Wire frontend directly to `OverviewView` + `AppointmentsByDayView` + `TopProfessionalsView` with zero backend changes; accept today/MTD filter only | 0.5h backend (permission only) + 5h frontend | Low | 7/10 (no period filter for week/month) |

**Auto-decision (P1 + P5):** Approach B selected. Highest completeness at lowest risk. Eliminates the duplicate-endpoint problem while delivering a complete dashboard.

---

## 0D. Mode-Specific Analysis — SELECTIVE EXPANSION

**Hold Scope Analysis:**

S-067: Well-scoped. 13pts of frontend catch-up. All endpoints confirmed working (Sprint 15 tests green). No scope changes needed.

S-068: Scope is valid but implementation approach is wrong (see 0B/0C-bis). Repointing to Approach B fixes this without story point change. Keep 8pts.

S-069: Valid feature, high risk on browser coverage and DPA enforcement. Keep in scope with explicit risk mitigations: browser detection UI + fallback textarea clearly specified, DPA seed data sufficient for demo.

**Cherry-Pick Ceremony (auto-decided per autoplan SELECTIVE EXPANSION override):**

| Candidate | Description | Effort | Decision | Rationale |
|-----------|-------------|--------|----------|-----------|
| CP-1: Relax analytics permissions | Remove `_BILLING_MODULE` from `OverviewView`, `AppointmentsByDayView`, `TopProfessionalsView` | XS (3 lines) | ✅ ACCEPTED — add to S-068 scope | Required for Approach B; 3-line change; zero blast radius beyond access |
| CP-2: Add `?period=` to `OverviewView` | Support `today`/`week`/`month` filter on existing endpoint | S (1-2h) | ✅ ACCEPTED — add to S-068 backend | Directly serves S-068 acceptance criteria; no new model needed |
| CP-3: Add revenue to `OverviewView` | Sum TISS guides (submitted+paid) per period | S (1h) | ✅ ACCEPTED — add to S-068 backend | Already aggregated in billing views; copy pattern |
| CP-4: Browser detection for S-069 | Show "Seu navegador não suporta ditado de voz. Use o campo de texto abaixo." with textarea fallback when `!window.SpeechRecognition` | XS | ✅ ACCEPTED — add to S-069 frontend | Mitigates P5 risk; fallback already mentioned in plan, just needs explicit spec |
| CP-5: DPA signing UI | Build `/settings/dpa` page for tenant admins to sign DPA and activate AI features | L (separate story) | ➡ DEFER to TODOS.md | Pre-GA blocker; not Sprint 16 scope; too large for cherry-pick |
| CP-6: Definition of Done enforcement | Add frontend checklist to story template; require UI before story closes | N/A (process) | ➡ DEFER to TODOS.md | Engineering process change; not a code change |
| CP-7: `arrived_at`/`started_at` on Appointment | Add check-in timestamps to enable real wait time metrics | M (migration + UI) | ➡ DEFER to TODOS.md | Prerequisite for fill rate; belongs in Sprint 17 with digital check-in |

---

## 0E. Temporal Interrogation

**HOUR 1 (S-067 — MFA frontend):**
- `app/auth/mfa/page.tsx` created; OTP input renders; auto-submit fires at 6 digits
- Risk: `django-otp` QR code response format — need to verify `setup/` endpoint actually returns `otpauth://` URI vs base64 image

**HOUR 2-4 (S-067 — Safety badge, CID10, PDF, Waitlist):**
- `SafetyBadge.tsx` polling loop; `SafetyAlertModal.tsx` with acknowledge form
- `CID10Suggest.tsx` debounce + suggestion chips
- "Imprimir Receita" button wired to PDF endpoint
- Waitlist page table
- Risk: CORS / blob handling for PDF download in Next.js — needs `fetch` + `URL.createObjectURL`

**HOUR 5 (S-068 — permission cleanup + period filter):**
- Remove `_BILLING_MODULE` from 3 views (3 lines)
- Add `?period=` to `OverviewView` (20-30 lines)
- Add revenue sum to `OverviewView` (5-10 lines)
- KPI card frontend components
- Risk: Period "week" = ISO week or last 7 days? Plan says "current ISO week" — clarify in implementation

**HOUR 6 (S-068 — dashboard frontend + S-069 scribe):**
- `app/(dashboard)/page.tsx` full ops dashboard
- `ScribeButton.tsx`, `SOAPEditor.tsx`
- `AIScribeSession` model + migration `0013_aiscribesession.py`
- `ClinicalScribe.generate_soap()` service
- 2 new endpoints + URL registration
- Risk: Claude response parsing — SOAP JSON may have markdown fencing; need robust `json.loads` with regex fallback

**HOUR 6+ (tests + DPA check):**
- 6 backend tests for S-069 (feature flag, DPA, valid/empty transcription, accept endpoint)
- 4 frontend tests
- Risk: `AIScribeSession` migration — emr now at `0013`; check for conflicts

---

## 0F. Mode Selection

**SELECTIVE EXPANSION confirmed.** Sprint 16 as written is the right scope — S-067 closes the UI debt, S-068 gives pilots a dashboard, S-069 kicks off Phase 2 AI. Accepted cherry-picks (CP-1, 2, 3, 4) refine the implementation approach without adding story points. Deferred items (CP-5, 6, 7) go to TODOS.md.

---

## CLAUDE SUBAGENT (CEO — strategic independence) [subagent-only]

> **S-068 is a redundant build — CRITICAL.** `OverviewView` already returns today + MTD KPIs. `AppointmentsByDayView` already returns sparklines. `TopProfessionalsView` already returns top-N professionals. Building a new `ClinicOpsView` creates two sources of truth that will diverge. Fix: extend existing views.
>
> **S-069 compliance liability — HIGH.** DPA check (`dpa_signed_date is not None`) is trivially bypassable by any admin. No DPA signing flow exists in the product. In Brazilian healthcare, sending voice health data to an external LLM without verified consent is a real ANPD risk. Fix: legal sign-off + build DPA signing UI before GA.
>
> **Fill rate metric is broken for new clinics — HIGH.** Requires `Schedule`/`TimeSlot` config. Week-3 pilots won't have this. A null fill rate on the retention dashboard defeats the stated purpose. Fix: use cancellation rate (already computed) as the headline KPI for unconfigured clinics.
>
> **`wait_time_avg` is a phantom metric — CRITICAL.** `Appointment` has no `arrived_at` or `started_at`. `WaitingTimeView` already returns zeros for this reason. Shipping a dashboard with a field that always reads null/0 erodes pilot trust. Fix: defer or remove from S-068 AC.
>
> **Web Speech API = Chrome monoculture — MEDIUM.** Brazilian clinics use Android + Firefox. A feature that works on 60% of devices isn't a scribe. Fix: browser detection + clear fallback.
>
> **S-067 is an organizational debt signal — MEDIUM.** 13 points of catch-up frontend work exists because Sprint 15 shipped backend-only. Pattern risk if definition-of-done isn't fixed.

---

## CEO DUAL VOICES — CONSENSUS TABLE [subagent-only]

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                              Claude  Codex  Consensus
  ────────────────────────────────────── ─────── ─────── ─────────
  1. Premises valid?                      NO      N/A    FLAGGED (P2, P4 false)
  2. Right problem to solve?             YES      N/A    CONFIRMED
  3. Scope calibration correct?          PARTIAL  N/A    FLAGGED (S-068 approach wrong)
  4. Alternatives sufficiently explored?  NO      N/A    FLAGGED (Approach B not in plan)
  5. Competitive/market risks covered?   PARTIAL  N/A    FLAGGED (browser coverage, DPA)
  6. 6-month trajectory sound?           YES      N/A    CONFIRMED (with fixes applied)
═══════════════════════════════════════════════════════════════
CONFIRMED = both agree. DISAGREE = models differ (→ taste decision).
Missing voice = N/A (not CONFIRMED). Single critical finding from one voice = flagged regardless.
```

---

## Review Sections

### Section 1: Architecture Review

S-067 architecture is clean — pure frontend consuming existing Sprint 15 endpoints. No backend changes needed; all endpoints already registered in `apps/emr/urls.py`.

S-068 (with Approach B): removing `_BILLING_MODULE` from 3 views and extending `OverviewView` with `?period=` is a local change. No new service layer, no new model. The period filter adds a conditional `filter` to the existing queryset — low coupling risk. Confirm `start_time__date` vs `appointment_date` field name consistency across existing views before implementation.

S-069: `AIScribeSession` in `apps/emr/` is architecturally correct — it's encounter-linked and belongs in EMR. `ClinicalScribe` as a service in `apps/emr/services/` follows the existing `PrescriptionPDFGenerator` pattern from Sprint 15. `ClaudeGateway.complete()` reuse is correct. One concern: the `generate_soap()` method should handle Claude returning markdown-fenced JSON (e.g., ` ```json\n{...}\n``` `) — the raw `json.loads()` will fail on this. Add a strip-fence preprocessing step.

**Finding (AUTO-FIX): Add JSON fence stripping to `ClinicalScribe.generate_soap()` before `json.loads()`.**

### Section 2: Error & Rescue Map

| Scenario | Endpoint / Component | Failure Mode | Recovery |
|----------|---------------------|--------------|----------|
| TOTP QR code decode fails | `GET /auth/mfa/setup/` | API returns non-URI `otpauth` string | Show raw text + "copy URI" fallback |
| Safety badge polling timeout (>10s) | `SafetyBadge.tsx` | Status still "pending" after 5 polls | Show amber "Verificando..." indefinitely; allow manual refresh |
| CID10 LLM degraded | `POST /cid10-suggest/` | Returns `degraded: true` | Suggestion panel hidden; textarea works normally |
| PDF blob CORS / empty response | `GET /prescriptions/{id}/pdf/` | fetch fails | Show "Erro ao gerar PDF" toast |
| `OverviewView` with period=week, zero data | `GET /analytics/overview/?period=week` | All zeros | Frontend shows "Sem dados neste período" empty state |
| `AIScribeSession` LLM timeout | `POST /encounters/{id}/scribe/` | `ClaudeGateway` raises `LLMGatewayError` | Return 503 `{"error": "Serviço de IA indisponível. Tente novamente."}` |
| SOAP JSON parse fails (markdown fenced) | `ClinicalScribe.generate_soap()` | `json.loads` raises | Strip fence, retry parse; if still fails, return 500 with degraded flag |
| DPA not signed | `POST /encounters/{id}/scribe/` | `dpa_signed_date` is null | Return 403 `{"dpa_required": true, "dpa_url": "/settings/dpa"}` |
| Web Speech API unsupported | `ScribeButton.tsx` | `!window.SpeechRecognition && !window.webkitSpeechRecognition` | Show fallback textarea with clear label |
| `AIScribeSession` accept — note creation fails | `POST /scribe/{session_id}/accept/` | `ClinicalNote.objects.create()` raises | Return 500; session NOT marked accepted; client retries safely |

### Section 3: Security & Threat Model

**MFA (S-067):** TOTP backup codes are generated server-side, shown once, downloadable as TXT. Ensure the download is served with `Content-Disposition: attachment` and the codes are NOT stored in plaintext (Sprint 15 should hash them — confirm in `TOTPDevice` model). The frontend TXT download is client-side `Blob` generation from the API response — codes are in-memory only, which is correct.

**CID10 / Safety (S-067):** No new security surface — all endpoints existed in Sprint 15.

**AI Scribe DPA check (S-069):** The `AIDPAStatus.dpa_signed_date is not None` check is necessary but not sufficient. Any superuser can bypass it by inserting a row. For demo/pilot: acceptable. For GA: needs a locked, auditable signing flow. Flag as pre-GA blocker.

**`AIScribeSession` data retention:** Voice transcriptions are PHI (dados sensíveis per LGPD). The model stores `raw_transcription TextField` indefinitely. Need a retention policy (auto-delete after 90 days?) before GA. Defer to TODOS.md.

**No new injection surfaces** in S-067/S-068. S-069 scribe endpoint takes user-supplied transcription text that is passed to Claude — Claude prompt injection is a theoretical risk but mitigated by the structured system prompt and the fact that the output is a SOAP note, not executable code.

### Section 4: Data Flow & Interaction Edge Cases

**S-067 — CID10 debounce race condition:** If user types fast, pauses 1.5s, then types again immediately, the first request may resolve after the second is issued. The component must cancel the first request on new input (`AbortController`). Without this, a slower response for an earlier query overwrites the suggestion panel. Add `AbortController` to `CID10Suggest.tsx` spec.

**S-067 — Safety badge polling:** The plan says "polling every 2s for 10s". If the user navigates away from the prescription builder mid-poll, the interval must be cleared (`clearInterval` in `useEffect` cleanup). Without this, the component leaks memory and may attempt to set state on an unmounted component.

**S-068 — Period boundary (ISO week vs calendar week):** The plan says "current ISO week". Weeks start Monday in Brazil. Confirm `TruncWeek` (Django) vs manual `date - date.weekday()` calculation. Using the wrong boundary will show wrong data on Mondays.

**S-069 — concurrent accepts:** If the doctor clicks "Salvar como Evolução" twice quickly, two `ClinicalNote` records could be created for the same `AIScribeSession`. The accept endpoint should check `session.accepted` before creating the note and return 409 if already accepted.

### Section 5: Code Quality Review

S-067 follows the existing Next.js patterns in the frontend (per Sprint 12 prior review). The `SafetyBadge` + `SafetyAlertModal` decomposition is clean.

S-068 (Approach B): the `?period=` extension to `OverviewView` should use a clean, validated query param handler, not `request.query_params.get("period", "today")` without a whitelist. Add: `period = request.query_params.get("period", "today"); if period not in ("today", "week", "month"): period = "today"`.

S-069 `ClinicalScribe.generate_soap()`: should validate that `transcription` is non-empty before calling the LLM. The view spec says 400 for `< 10 chars` — validate at the view layer, not in the service, to keep the service pure.

### Section 6: Test Review

**Sprint 15 integration coverage:** 355 tests green. Sprint 16 tests as specified:

S-067 frontend tests (Vitest):
- MFA QR renders from API response ✓
- Safety badge spinner → badge transition ✓
- CID10 debounce (suggest panel not shown before 1.5s) ✓
- "Imprimir Receita" disabled for unsigned prescription ✓
- **MISSING:** `SafetyAlertModal` acknowledge form requires min 10 chars for contraindication
- **MISSING:** CID10 `AbortController` — no stale response overwrites panel

S-069 backend tests (specified):
- Feature flag OFF → 403 ✓
- DPA unsigned → 403 `{"dpa_required": true}` ✓
- Valid transcription → SOAP 4 fields non-empty ✓
- Accept → `ClinicalNote` created ✓
- Empty transcription → 400 ✓
- `accepted=True` after accept ✓
- **MISSING:** Concurrent accept (double-click) → second call returns 409
- **MISSING:** LLM markdown-fenced JSON response → parsed correctly

### Section 7: Performance Review

S-068 `OverviewView` with `?period=` — no new indexes needed if using the existing `start_time` index. The `TruncDate("start_time")` annotation has an index scan on `start_time__date__gte=since` which is already in use. For `week` period, the filter is `start_time__date__range=(week_start, today)` — also index-covered. Response time < 200ms confirmed assuming existing index coverage.

S-069 scribe endpoint — synchronous LLM call is the bottleneck. A 30-second voice transcription → ~800 words → ~1200 tokens → Claude Sonnet response time ~3-5s. This is acceptable for the use case (doctor is finishing typing anyway). No Celery needed. Do NOT add async here — synchronous is simpler and the 5s wait is UX-acceptable for a scribe feature.

### Section 8: Observability & Debuggability Review

Existing `logger` calls in `apps/emr/views_safety.py` and `apps/ai/services_cid10.py` cover current endpoints. S-069 should log:
- `AIScribeSession` created (session_id, encounter_id, tokens_in, tokens_out)
- `ClinicalNote` created from session (note_id, session_id)
- DPA check failures (tenant, user_id — no PHI)
- LLM errors (error type, schema_name — no transcription content)

The `raw_transcription` must NOT be logged (PHI under LGPD). Add a comment in `ClinicalScribe` noting this constraint.

### Section 9: Deployment & Rollout Review

Migration `0013_aiscribesession.py` — must be generated with `makemigrations emr` after model definition. Confirm current latest migration is `0012_*` in `apps/emr/migrations/`. Migration adds one table to the tenant schema — backward-safe, no existing data affected.

Feature flag `ai_scribe` default OFF — tenant admins activate manually after DPA signing. Correct rollout posture. No blast radius.

`_BILLING_MODULE` removal from analytics views — affects all tenants on deploy. Existing billing dashboards unaffected (they still work with the permission; non-billing tenants just now see the data too). Low risk — analytics data is clinic-internal, not cross-tenant.

### Section 10: Long-Term Trajectory Review

This sprint correctly positions Vitali for v1.1.0:
- Closing the Sprint 15 UI debt (S-067) makes the product shippable to non-early-adopter users
- The ops dashboard (S-068) directly addresses the "pilot churn week 3" risk
- AI Scribe (S-069) is the right Phase 2 AI kickoff — voice is the highest-friction part of clinical documentation

6-month trajectory concern: the fill rate and wait time metrics are deferred (correct decision) but the dashboard will launch without them. This is fine as long as the UI design accommodates "Configure seus horários para ver a taxa de ocupação" CTAs rather than empty metric cards. Design must plan for graceful partial data.

Long-term: `AIScribeSession` table will grow fast once adoption picks up. Plan a quarterly cleanup job that archives or deletes non-accepted sessions. This is not a Sprint 16 blocker but should be a Sprint 18-19 ticket.

### Section 11: Design & UX Review (UI scope detected)

**S-067:**
- MFA enrollment is a high-stakes flow (users can lock themselves out). The QR → code → backup codes sequence must have clear progress indication. "Step 2 of 3" header or similar. Download backup codes must be gated: user cannot close modal without either downloading or explicitly acknowledging risk.
- Safety badge colors: green "Seguro" / amber ⚠ / red 🚫 map to `safe`/`warning`/`contraindication` severity. Ensure color-blind safe (add text labels, not color only).
- CID10 chips: confidence % should be subtle secondary text, not primary. The code + description is what the doctor selects; confidence is a signal for trust calibration.

**S-068:**
- KPI cards should show trend (↑ ↓ →) vs prior period once period comparison is available. For launch, show absolute value + "comparativo indisponível" for first week.
- Sparkline: 7-day bar chart must label days in PT-BR (Seg, Ter, Qua...) not English abbreviations.
- Empty state copy: "Você ainda não tem consultas hoje. Verifique se sua agenda está configurada." is more helpful than a generic empty state.

**S-069:**
- LGPD consent banner on first use ("Esta funcionalidade envia transcrições de voz ao Claude (Anthropic)...") must be dismissible with persistent storage (localStorage or user preference). Showing it every encounter is noise.
- `SOAPEditor`: the 4 panels (S/O/A/P) should map to Portuguese labels prominently: **Subjetivo** (queixa do paciente), **Objetivo** (exame físico), **Avaliação** (hipótese diagnóstica), **Plano** (tratamento). Include these as field headers, not just tooltips.
- "Iniciar Ditado" button should show recording state clearly: pulsing red dot + duration counter. Silence detection (no speech for 3s) auto-stops and submits.

---

## NOT in Scope (Deferred to TODOS.md)

| Item | Rationale |
|------|-----------|
| DPA signing UI (`/settings/dpa`) | Pre-GA blocker; separate story; ~L effort |
| `arrived_at`/`started_at` on Appointment | Prerequisite for wait time; belongs with digital check-in (Sprint 17) |
| `AIScribeSession` data retention policy | Pre-GA LGPD compliance; Sprint 18-19 ticket |
| Server-side transcription (Whisper API) | Fallback for non-Chrome devices; Phase 2 AI continuation |
| Definition of Done process enforcement | Engineering process change; not a code change |
| `Fill rate` metric via Schedule config | Operational, not engineering; activate when pilots configure schedules |

---

## What Already Exists

| S-068 Need | Existing Code | File |
|------------|---------------|------|
| Today's appointment totals | `OverviewView.get()` | `apps/analytics/views.py:31` |
| 7-day sparkline | `AppointmentsByDayView.get()` | `apps/analytics/views.py:92` |
| Top professionals | `TopProfessionalsView.get()` | `apps/analytics/views.py` |
| LLM gateway for S-069 | `ClaudeGateway.complete()` | `apps/ai/gateway.py` |
| Feature flag infrastructure | `get_tenant_ai_config()` | `apps/ai/services.py` |
| DPA gate model | `AIDPAStatus` | `apps/core/models.py` (Sprint 15) |
| Circuit breaker / rate limiter | `apps/ai/circuit_breaker.py`, `apps/ai/rate_limiter.py` | Sprint 9 |

---

## Error & Rescue Registry

| # | Error | Scenario | Recovery Path |
|---|-------|----------|---------------|
| E1 | SOAP JSON not parseable (markdown fenced) | Claude returns ` ```json\n{...}\n``` ` | Strip fences, retry `json.loads`; fail → 500 with degraded flag |
| E2 | DPA not signed | Tenant missing `AIDPAStatus` row or `dpa_signed_date` null | 403 `{"dpa_required": true, "dpa_url": "/settings/dpa"}` |
| E3 | Speech recognition not supported | Non-Chrome/Edge browser | Show fallback textarea with instructions |
| E4 | Concurrent accept on same scribe session | Double-click "Salvar" | Check `session.accepted` before create; return 409 if already done |
| E5 | Period param invalid | `?period=garbage` in clinic ops | Whitelist validation, default to "today" |
| E6 | PDF blob CORS fail | Network issue or unsigned prescription | Toast "Erro ao gerar PDF. Verifique se a receita está assinada." |

---

## Failure Modes Registry

| # | Failure | Likelihood | Impact | Mitigation |
|---|---------|-----------|--------|------------|
| F1 | fill_rate=null for all new pilots | HIGH | Pilot retention risk (reason S-068 was built) | Replace headline KPI with cancellation_rate; add "Configure horários" CTA |
| F2 | wait_time always 0 | HIGH | Trust erosion | Remove from S-068 AC; add placeholder "Em breve — aguarda check-in digital" |
| F3 | AI Scribe Chrome-only at beta | MED | Differentiator lost for 30-40% of clinic devices | Browser detection + fallback; defer Whisper to Sprint 17 |
| F4 | DPA check bypassable in prod | MED | ANPD compliance risk | Acceptable for beta with DPA seeds; pre-GA blocker for real signing flow |
| F5 | Double source of truth (analytics) | MED (if Approach A taken) | Data inconsistency between `/overview/` and `/clinic-ops/` | Approach B prevents this by extending existing views |

---

## Scope Expansion Decisions

| Cherry-pick | Decision | Impact |
|-------------|----------|--------|
| CP-1: Relax analytics permissions | ✅ ACCEPTED | `_BILLING_MODULE` removed from 3 views; S-068 frontend can call existing endpoints |
| CP-2: Add `?period=` to `OverviewView` | ✅ ACCEPTED | Extends existing endpoint to support today/week/month filter |
| CP-3: Add revenue to `OverviewView` | ✅ ACCEPTED | Sum TISS guides (submitted+paid) added to period response |
| CP-4: Browser detection for S-069 | ✅ ACCEPTED | Explicit fallback textarea spec added to S-069 frontend AC |
| CP-5: DPA signing UI | ➡ DEFERRED | TODOS.md — pre-GA story |
| CP-6: Definition of Done enforcement | ➡ DEFERRED | TODOS.md — process change |
| CP-7: `arrived_at`/`started_at` on Appointment | ➡ DEFERRED | TODOS.md — Sprint 17 with digital check-in |

---

## Completion Summary

| Section | Status | Issues Found |
|---------|--------|--------------|
| 0A Premises | ⚠️ 2 false premises found | P2 (no new endpoint needed), P4 (wait_time uncomputable) |
| 0B Existing code | ✅ | 80% of S-068 backend already exists |
| 0C Dream state | ✅ | Delta documented; path to 12-month ideal clear |
| 0C-bis Alternatives | ✅ | Approach B selected (leverage existing) |
| 0D Cherry-picks | ✅ | 4 accepted, 3 deferred |
| 0E Temporal | ✅ | 6-hour implementation path viable |
| Section 1 (Arch) | ✅ | 1 fix: JSON fence stripping in `generate_soap()` |
| Section 2 (Errors) | ✅ | 10 error paths mapped |
| Section 3 (Security) | ⚠️ | DPA check weak; PHI retention note added |
| Section 4 (Data flow) | ⚠️ | 3 edge cases: AbortController, interval cleanup, concurrent accept |
| Section 5 (Code quality) | ✅ | Period param whitelist; transcription validation placement |
| Section 6 (Tests) | ⚠️ | 4 missing test cases added to spec |
| Section 7 (Performance) | ✅ | Indexes sufficient; sync LLM call acceptable |
| Section 8 (Observability) | ✅ | Logging spec for S-069; PHI non-logging constraint noted |
| Section 9 (Deployment) | ✅ | Migration `0013` backward-safe; permission change low-risk |
| Section 10 (Trajectory) | ✅ | Sprint correctly scoped for v1.1.0 |
| Section 11 (Design) | ⚠️ | 5 UX notes: progress indicator, color-blind safety, PT-BR labels, LGPD banner persistence, silence detection |

**Overall verdict: PROCEED with revisions.** Plan is strategically sound. Two false premises corrected (Approach B for S-068; `wait_time`/`fill_rate` deferred). 4 cherry-picks accepted. Sprint 16 as revised delivers a complete and shippable v1.1.0.

---

**Phase 1 complete.** [subagent-only]. Claude subagent: 5 issues (2 critical, 2 high, 1 medium). Codex: N/A.
Consensus: 2/6 confirmed, 4 flagged → addressed in cherry-picks and section findings.
Passing to Premise Gate.

---

## ✅ PREMISE GATE — CONFIRMED

**User confirmed all three premises (2026-04-06):**
- P1: Use Approach B for S-068 — extend existing views, no new `views_clinic_ops.py` ✅
- P2: Remove `fill_rate` and `wait_time_avg_min` from S-068 AC; replace with cancellation_rate + CTAs ✅
- P3: S-069 DPA: seed data for demo, signing UI deferred to TODOS.md ✅

---

## ⚠️ PREMISE GATE — Confirmation Required (COMPLETED)

Before Phase 2, please confirm the following premises that affect implementation approach:

**Revised Plan Summary:**
- S-067: No changes (13pts, pure frontend catch-up)
- S-068: Implementation approach changed from "new ClinicOpsView" → "extend existing OverviewView + relax permissions" (Approach B). Same 8pts, less backend risk, no duplicate endpoints. `fill_rate` and `wait_time_avg` removed from AC (infeasible without Schedule config / check-in timestamps). Revenue via TISS guides added.
- S-069: Explicit browser detection + fallback textarea added to AC. DPA signing UI deferred to TODOS.md.

**Premises requiring your confirmation:**

> **P1:** Use Approach B for S-068 — extend `OverviewView` with `?period=` and revenue, relax `_BILLING_MODULE` permission, wire frontend to existing endpoints. Do NOT build a new `views_clinic_ops.py`.
>
> **P2:** Remove `fill_rate` and `wait_time_avg_min` from S-068 acceptance criteria (infeasible: no Schedule config data, no Appointment timestamps). Replace headline metric with `cancellation_rate`.
>
> **P3:** Proceed with S-069 as scoped (Web Speech API, feature flag, DPA seed data for demo). DPA signing UI is a TODOS.md item for a future sprint, not Sprint 16 scope.

---

---

# AUTOPLAN — Phase 2: Design Review

**Mode:** All AskUserQuestions auto-decided | **UI scope:** S-067 (MFA, safety, CID10, PDF, waitlist), S-068 (ops dashboard), S-069 (AI scribe)
**Design system:** DESIGN.md present — Vitali clinical-clean SaaS, brand-600 = #2563eb, semantic status colors
**Mockups:** $D not configured — proceeding with text-only review

**Initial score estimate:** 5/10 — plan specifies component names but lacks IA hierarchy, interaction state tables, and emotional arc for clinical flows.

---

## Design Dual Voices [subagent-only]

> **Claude subagent design review:**
> - MFA enrollment lacks progress indicator spec — "3 steps" is mentioned but no step header or breadcrumb design. Risk: users cancel mid-flow because they don't know how long it takes (MFA is already intimidating).
> - Safety badge: spinner → badge transition is correct concept but "within 5s" isn't a UX spec — it's a perf requirement. The loading state must communicate progress, not just spin.
> - S-068 dashboard: "5 KPI cards" will become 3-column icon-circle grid unless spec prevents it. This is AI Slop pattern #1 for app UI (dashboard-card mosaics violate App UI Rules).
> - CID10 suggestion chips: plan says "3 chips" but doesn't specify what happens when user already has a CID-10 filled in. Replace? Confirm? This is a real clinical UX risk.
> - LGPD banner: "first use" needs localStorage persistence spec or it reappears every encounter.
> - SOAPEditor: 4 panels need explicit layout — horizontal tabs or vertical stacked? On a 13" clinical laptop both approaches have tradeoffs.

---

## Pass 1: Information Architecture — 5/10

**What to 10:** The plan names components but doesn't define what appears above the fold, what's secondary, what requires scroll.

**Critical IA gaps identified and auto-fixed:**

**S-067 MFA Enrollment (`/profile/security`):**
```
Above fold:  Security status card (MFA enabled/disabled badge + last-used date)
             "Configurar Autenticação de Dois Fatores" primary button
Below fold:  Backup codes section (visible after enrollment only)

Enrollment modal sequence:
  Step 1 of 3: QR Code — "Escaneie com seu app autenticador"
               [QR image] + manual code (monospace, copyable)
               [Continuar →]
  Step 2 of 3: Verificação — "Digite o código gerado pelo app"
               [6-digit OTP input, auto-submit on 6th digit]
  Step 3 of 3: Códigos de backup — "Guarde estes códigos em local seguro"
               [8 codes in 2-column grid]
               [Baixar TXT] (primary) | [Fechar sem baixar] (secondary, requires confirm)
```

**S-068 Dashboard (`/dashboard`):**
```
Above fold (primary workspace):
  Row 1: Period selector tabs [Hoje | Semana | Mês]
  Row 2: 4 KPI metric numbers (large type) — total appts, completed, cancellation rate, revenue
  Row 3: 7-day sparkline (full width)

Below fold:
  Top 3 Professionals table (name, specialty, appointment count)
  Future: Fill rate CTA | Wait time CTA (placeholder rows with lock icon + "Configure para ativar")
```

**S-069 AI Scribe (in encounter detail):**
```
Encounter detail layout (existing):
  [Patient info header]
  [Encounter data form]
  [Clinical Notes section]
  → ADD HERE: [AI Scribe bar — "Iniciar Ditado" button, LGPD notice on first use]
  → AFTER DICTATION: [SOAPEditor — 4 stacked panels, full-width]
  → [Salvar como Evolução — primary button]
```

**Auto-decision:** All IA specs accepted and added to plan (P2: in blast radius, <1d CC).

---

## Pass 2: Interaction State Coverage — 4/10 → 8/10 after fix

**Before fix:** Plan specifies success states only. No loading, empty, error, or partial specs.

**Interaction state table (auto-generated and added to spec):**

| Feature | Loading | Empty | Error | Success | Partial |
|---------|---------|-------|-------|---------|---------|
| MFA QR code | Spinner in modal step 1 area | N/A | "Erro ao gerar QR. Tente novamente." + retry | QR displayed | N/A |
| Safety badge | Gray spinner, "Verificando..." label | N/A (not applicable) | Amber badge "Verificar manualmente" | Green "Seguro" / Amber ⚠ / Red 🚫 | "Verificando" if still polling at 10s |
| CID10 suggestion panel | 3 skeleton chips (gray, animated) after 1.5s debounce wait | Hidden (< 20 chars) | Hidden + console.warn (fail-open, field still editable) | 3 colored chips with code + description + confidence | 1-2 chips (LLM returned < 3 valid codes) |
| Prescription PDF | Loading state on button: spinner + "Gerando..." disabled | N/A | Toast "Erro ao gerar PDF. Verifique se a receita está assinada." | New tab opens with PDF | N/A |
| Waitlist page | Table skeleton (3 row placeholders) | "Nenhum paciente na lista de espera." + link to booking | Toast "Erro ao carregar. Tente novamente." + retry | Table with entries | Partial: show loaded entries, spinner in pagination |
| KPI dashboard | Skeleton cards (same grid structure, animated) | "Sem dados para este período." per card (not page-level) | Per-card "Erro" badge + retry icon | Numbers with trend indicators | Some cards loaded, others still loading (allowed) |
| AI Scribe button | Pulsing red dot + "Gravando... 0:12" duration counter | N/A | "Seu navegador não suporta ditado. Use o campo abaixo." | Transcription sent → "Processando com IA..." | N/A |
| SOAPEditor | 4 panels in skeleton state ("Gerando...") | N/A | "Erro ao gerar evolução. Tente novamente." + textarea fallback | 4 panels pre-filled, all editable | Some panels filled, others empty (allowed — doctor fills manually) |

**Auto-decision:** State table accepted (P1: highest completeness). Written to design spec.

---

## Pass 3: User Journey & Emotional Arc — 6/10 → 8/10

**S-067 MFA Enrollment:**
```
STEP | USER DOES                    | USER FEELS          | SPEC COVERS?
-----|------------------------------|---------------------|-------------
1    | Sees security settings page  | "Do I need to do this?" | ✅ Status badge (enabled/disabled) tells them current state
2    | Clicks "Configurar MFA"      | Uncertain — "How long?" | ✅ Step 1 of 3 header
3    | Scans QR, waits for code     | Slightly anxious    | ⚠️ ADD: "O código muda a cada 30 segundos" hint text under OTP input
4    | Sees backup codes            | "I need to save these" | ✅ Download gated with confirm
5    | Closes modal                 | Confident + secure  | ✅ Status badge updates to "Ativo"
```

**S-068 Ops Dashboard:**
```
STEP | USER DOES                    | USER FEELS          | SPEC COVERS?
-----|------------------------------|---------------------|-------------
1    | Opens /dashboard on Monday   | "How was last week?" | ✅ Period selector [Hoje|Semana|Mês]
2    | Sees today's KPIs            | "Is this a good day?" | ✅ KPI numbers with trend (↑↓→)
3    | Sees cancellation rate spike | "Why is this high?"  | ⚠️ ADD: KPI card shows "3 cancelamentos hoje" — make count clickable → filtered appointment list
4    | Checks sparkline             | "Is this a trend?"  | ✅ 7-day view shows pattern
```

**S-069 AI Scribe:**
```
STEP | USER DOES                    | USER FEELS          | SPEC COVERS?
-----|------------------------------|---------------------|-------------
1    | Sees LGPD banner first use   | "Is this safe?"     | ✅ Explicit consent notice
2    | Clicks "Iniciar Ditado"       | "Is it recording?"  | ✅ Pulsing red dot + counter
3    | Stops speaking, waits        | "Did it work?"      | ⚠️ ADD: "Processando com IA..." intermediate state between stop and SOAP appearing
4    | Sees SOAP pre-filled         | Delight if good     | ✅ 4 editable panels
5    | Edits S section              | "Can I trust this?" | ⚠️ ADD: confidence indicator on each panel ("Gerado com IA — revise antes de salvar" subtle tag)
6    | Saves as evolution           | Done                | ✅ "Salvar como Evolução" button
```

**Auto-decision:** Journey gaps accepted and spec updated (P2).

---

## Pass 4: AI Slop Risk — 7/10

**Classifier:** APP UI (clinical dashboard, data-dense, task-focused).

**App UI Hard Rules check:**

| Pattern | Present in plan? | Action |
|---------|-----------------|--------|
| Dashboard-card mosaic | ⚠️ RISK — "5 KPI cards" spec without layout constraint | **Fixed:** IA spec above uses 1 row of 4 large metric numbers, NOT a card grid. Dense metrics over mosaic. |
| Thick borders / decorative gradients | Not specified → defaults OK in Vitali's slate/brand system | No action |
| Icons in colored circles | ⚠️ RISK — KPI cards often get icons-in-circles treatment | **Added to spec:** KPI values displayed as large type (text-4xl) with secondary label below. No icon circles. |
| Colored left-border cards | Not specified | Confirm: AI Slop blacklist item #8 — explicitly exclude |

**Vitali Design System alignment:**
- Status colors for safety badges: `bg-red-50 text-red-700` for contraindication, `bg-yellow-50 text-yellow-700` for warning, `bg-green-50 text-green-700` for safe. ✅ Matches DESIGN.md semantic system.
- Safety badge 🚫 emoji must be replaced with inline SVG icon or `×` text — DESIGN.md principle: "Labels are full words in Portuguese, never cryptic icons alone." Keep emoji only as a design sketch; implementation uses text: "Contraindicado".
- CID10 chips: use `brand-50` background + `brand-700` text for selected chip, `slate-100` + `slate-700` for unselected. No colored-circle pattern.

**Auto-decision:** Emoji → text replacement added to spec. Card mosaic prevention added to spec. (P2)

---

## Pass 5: Design System Alignment — 8/10

DESIGN.md is present and detailed. Checking each new component against design tokens:

| Component | Token usage | Status |
|-----------|-------------|--------|
| MFA OTP input (6 digits) | Use existing `<Input>` pattern from shadcn; `border-slate-200` default, `border-brand-600` focus | ✅ |
| SafetyBadge | `bg-green-50/yellow-50/red-50` + matching text color per DESIGN.md severity system | ✅ |
| CID10 suggestion chips | `bg-brand-50 text-brand-700 border-brand-200` — matches existing chip/badge patterns | ✅ |
| KPICard | Large `text-4xl font-bold text-slate-900` for value; `text-sm text-slate-500` for label — matches data-density principle | ✅ |
| Sparkline | `brand-500` (#3b82f6) for bars — matches "chart lines" token use in DESIGN.md | ✅ |
| SOAPEditor panels | `bg-white border border-slate-200` with `text-slate-700` body — standard content panel | ✅ |
| ScribeButton recording state | Pulsing red dot: `bg-red-500 animate-pulse` — semantic red (recording = critical attention) | ✅ |

One gap: `TopProfessionalsTable` isn't specified beyond "compact ranked table." Apply DESIGN.md principle "Tables over cards when comparing rows." Use standard `<table>` pattern with `text-sm text-slate-800` cells, rank number in `text-slate-400`.

**Auto-decision:** TopProfessionalsTable spec added (P2).

---

## Pass 6: Responsive & Accessibility — 5/10 → 7/10

**Responsive:**
- S-068 dashboard: On mobile (375px), KPI row stacks 2×2. Sparkline full-width. TopProfessionalsTable shows rank + name only (hide appointment count on xs).
- MFA OTP: 6-digit boxes must be min 44px touch targets each. On mobile: `grid-cols-6 gap-2` with `h-14 w-10` each.
- SOAPEditor: On mobile, stacked panels scroll vertically. "Salvar como Evolução" sticky at bottom.

**Accessibility:**
- MFA OTP: Each input must have `aria-label="Dígito N do código TOTP"`. Auto-focus next input on digit entry.
- Safety badge: Color alone insufficient per DESIGN.md principle 3. Add `role="status"` + `aria-label="Verificação de segurança: Contraindicação"` to red badge.
- Sparkline: Add `aria-label="Consultas nos últimos 7 dias"` + `role="img"` to chart container.
- KPI cards: Each value must have a visually-hidden label for screen readers (the large number alone isn't meaningful).
- Touch targets: 44px minimum on all interactive elements (CID10 chips, waitlist cancel button, period selector tabs).

**Auto-decision:** A11y and responsive specs added (P2).

---

## Pass 7: Unresolved Design Decisions — 6 resolved, 0 deferred

| Decision | Resolution |
|----------|------------|
| SOAPEditor: tabs vs stacked panels | **Stacked (vertical)** — matches clinical note reading order (S → O → A → P); doctor reads top-to-bottom. Tabs hide content. |
| CID10: what happens if CID-10 already filled? | Show chips with "Substituir?" label. Click chip shows confirm: "Substituir [current] por [new]?" |
| LGPD banner: persist after dismiss? | `localStorage.setItem('vitali_scribe_lgpd_dismissed', '1')` — never show again after first dismiss. |
| Silence detection (auto-stop): duration? | 3s of silence auto-stops recording. Show countdown: "Parando em 3... 2... 1..." |
| MFA: "Fechar sem baixar" risk warning | Modal: "Você ainda não baixou seus códigos de backup. Se perder acesso ao app autenticador, não poderá fazer login. Fechar mesmo assim?" with destructive secondary button. |
| KPI trend indicator: what baseline? | Compare same period prior week. Today's count vs same weekday last week. "↑ 12% vs semana passada." |

---

## Design Review Completion Summary

| Pass | Score Before | Score After | Key Fix |
|------|-------------|-------------|---------|
| Pass 1 (IA) | 5/10 | 9/10 | Full IA hierarchy for 3 stories; enrollment flow spec |
| Pass 2 (States) | 4/10 | 8/10 | Complete interaction state table for all 8 UI features |
| Pass 3 (Journey) | 6/10 | 8/10 | Emotional arc for MFA, dashboard, scribe; 3 UX gap fixes |
| Pass 4 (AI Slop) | 7/10 | 9/10 | Emoji → text; card mosaic prevention; icon-circle ban |
| Pass 5 (Design Sys) | 8/10 | 9/10 | TopProfessionalsTable token spec; all tokens verified |
| Pass 6 (Responsive) | 5/10 | 7/10 | Mobile breakpoints; 44px touch targets; a11y ARIA labels |
| Pass 7 (Decisions) | 5/10 | 10/10 | 6 design decisions resolved inline |

**Overall: 5/10 → 8.6/10 after fixes.** Plan is design-complete for implementation. Run `/design-review` after shipping for visual QA.

**Phase 2 complete.** [subagent-only]. 6 design gaps fixed inline. 0 deferred.
Passing to Phase 3.

---

---

# AUTOPLAN — Phase 3: Eng Review

**Mode:** All AskUserQuestions auto-decided | [subagent-only] — Codex not available

---

## CLAUDE SUBAGENT (Eng — independent review) [subagent-only]

Key findings (independent, no prior phase context):
1. **S-068 duplicate analytics** (high) — `ClinicOpsView` duplicates `OverviewView` logic. Fix: Approach B (already confirmed in premise gate).
2. **`ClaudeGateway` client not pooled** (medium) — `complete()` creates `anthropic.Anthropic(...)` on every call. At 10x load with concurrent scribes, this creates new connection pools per request. Fix: lazy-cached `_client` on the class.
3. **`wait_time_avg` fields don't exist** (critical) — `Appointment.arrived_at`/`started_at` not on model. Already removed from AC in premise gate.
4. **`fill_rate` uncomputable for new tenants** (critical) — Already removed from AC in premise gate.
5. **Cross-tenant IDOR on scribe accept** (critical) — `POST /scribe/{session_id}/accept/` must verify `session.encounter.patient` belongs to the current tenant schema. In django-tenants this is schema-scoped by default, but must be explicitly verified.
6. **`AIDPAStatus.first().dpa_signed_date` AttributeError** (critical) — If no `AIDPAStatus` row exists for the tenant, `.first()` returns `None`, then `.dpa_signed_date` raises `AttributeError`. Must handle None case.
7. **`raw_transcription` stored unencrypted** (high) — Clinical speech is PHI under LGPD Art. 11. Should use `EncryptedTextField` like `cpf`. Pre-GA blocker.
8. **Web Speech API interim results complexity** (high) — `onresult` fires continuously; must handle `isFinal`, accumulate results, silence-detect. 2-3x more complex than plan estimates.
9. **SOAP JSON parsing unspecified** (high) — Claude can return markdown-fenced JSON or prose. Already flagged in Phase 1 Section 1; add explicit spec.
10. **`generate_mrn()` race condition** (medium) — Python-level increment without `SELECT FOR UPDATE`. Pre-existing issue, not Sprint 16 scope.

---

## ENG DUAL VOICES — CONSENSUS TABLE [subagent-only]

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                           Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ─────── ─────────
  1. Architecture sound?              PARTIAL  N/A    FLAGGED (Approach B fixes S-068; ClaudeGateway pooling)
  2. Test coverage sufficient?         NO      N/A    FLAGGED (4 missing critical tests)
  3. Performance risks addressed?     PARTIAL  N/A    FLAGGED (connection pooling; polling batching)
  4. Security threats covered?         NO      N/A    FLAGGED (IDOR; unencrypted PHI; DPA bypass)
  5. Error paths handled?              NO      N/A    FLAGGED (AIDPAStatus None; SOAP parse failure)
  6. Deployment risk manageable?      YES      N/A    CONFIRMED (migration 0013 backward-safe; flag default OFF)
═══════════════════════════════════════════════════════════════
```

---

## Section 1: Architecture — Dependency Graph

```
Sprint 16 — Component Dependency Graph

NEW (Sprint 16)                          EXISTING (Sprint 15 / earlier)
─────────────────────────────────────── ─────────────────────────────────────────
                                         ClaudeGateway (apps/ai/gateway.py)
                                           ↑
ClinicalScribe (apps/emr/services/)  ────► ClaudeGateway.complete()
    ↑                                      ↑
ScribeView (POST /scribe/)    ──────────── apps/emr/views_scribe.py
ScribeAcceptView              ──────────── apps/emr/views_scribe.py
    ↑                              ↑
AIScribeSession (NEW model)    Encounter (existing)
    apps/emr/migrations/0013       ↑
                                ClinicalNote (existing)

OverviewView (EXTENDED)  ◄──── S-068: add ?period= + revenue
    (apps/analytics/views.py)    (NO new file)
AppointmentsByDayView ◄─────── permission: _BILLING_MODULE → IsAuthenticated
TopProfessionalsView  ◄─────── permission: _BILLING_MODULE → IsAuthenticated

Frontend new components:
  ScribeButton.tsx  ──────────► Web Speech API (browser-native)
  SOAPEditor.tsx    ──────────► POST /encounters/{id}/scribe/
                                POST /encounters/{id}/scribe/{session_id}/accept/
  KPICard.tsx       ──────────► GET /analytics/overview/?period=
  Sparkline.tsx     ──────────► GET /analytics/appointments-by-day/?days=7
  TopProfessionalsTable.tsx ──► GET /analytics/top-professionals/
```

**Coupling concerns:**
- `ClinicalScribe` depends on `ClaudeGateway` and `AIDPAStatus` (cross-app import `apps.core.models`). Acceptable — same pattern as `CID10Suggester`.
- `AIScribeSession` FK → `Encounter` FK → `Patient` — 2 levels deep. Django select_related handles this.
- `ClinicalNote` created by accept endpoint — same model used elsewhere; no new coupling.

**Auto-decision (P1):** Architecture sound with Approach B confirmed. ClaudeGateway client pooling added to implementation spec.

---

## Section 2: Code Quality

**Issues auto-decided:**

1. **`AIDPAStatus` None guard** (critical — auto-fixed in spec):
   ```python
   # WRONG (crashes if no row):
   AIDPAStatus.objects.filter(tenant=...).first().dpa_signed_date is not None
   
   # CORRECT:
   dpa = AIDPAStatus.objects.filter(tenant=...).first()
   if not dpa or not dpa.dpa_signed_date:
       return Response({"dpa_required": True}, status=403)
   ```

2. **`ClaudeGateway` client pooling** (medium — auto-fixed in spec):
   ```python
   # Add to ClaudeGateway.__init__():
   self._client = None
   
   # In complete():
   if self._client is None:
       self._client = anthropic.Anthropic(api_key=self._api_key, timeout=float(self.timeout))
   ```
   Note: `ClaudeGateway` is instantiated per-request in the views. For true pooling, make it a module-level singleton or use Django's cache. For Sprint 16: lazy init on the instance is sufficient.

3. **SOAP JSON fence stripping** (high — added to spec):
   ```python
   def _parse_soap_response(raw: str) -> dict:
       # Strip markdown fences if present
       cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE)
       try:
           data = json.loads(cleaned)
       except json.JSONDecodeError:
           raise ValueError(f"Unparseable SOAP response: {raw[:200]}")
       required = {"s", "o", "a", "p"}
       if not required.issubset(data.keys()):
           raise ValueError(f"SOAP missing keys: {required - data.keys()}")
       return data
   ```

4. **Period param validation** (medium — already in Phase 1 Section 5, confirmed):
   ```python
   period = request.query_params.get("period", "today")
   if period not in ("today", "week", "month"):
       period = "today"
   ```

5. **`generate_mrn()` race** — pre-existing, not Sprint 16 scope. Log to TODOS.md.

---

## Section 3: Test Review

**Test diagram — all new codepaths:**

```
S-067 Frontend
├── MFA enrollment flow
│   ├── [Vitest] QR renders from API response ✅ (in plan)
│   ├── [Vitest] OTP auto-submits on 6th digit ⚠️ ADD
│   ├── [Vitest] "Fechar sem baixar" shows warning modal ⚠️ ADD
│   └── [Vitest] Backup codes TXT download triggers correctly ⚠️ ADD
├── Safety badge
│   ├── [Vitest] Spinner → badge on API response ✅ (in plan)
│   ├── [Vitest] Polling clears on unmount (no memory leak) ⚠️ ADD
│   └── [Vitest] Amber badge when status=warning ⚠️ ADD
├── CID10 panel
│   ├── [Vitest] Panel not shown before 1.5s debounce ✅ (in plan)
│   ├── [Vitest] AbortController cancels stale request ⚠️ ADD
│   └── [Vitest] "Substituir?" confirm shown when CID already filled ⚠️ ADD
└── PDF / Waitlist ✅ (sufficient as specced)

S-068 Backend
├── OverviewView with period=today/week/month
│   ├── [Django] period=today returns today's data ⚠️ ADD
│   ├── [Django] period=week returns ISO week data ⚠️ ADD
│   ├── [Django] period=month returns current month data ⚠️ ADD
│   ├── [Django] zero data → all zeros, no error ✅ (in plan)
│   ├── [Django] invalid period param → defaults to today ⚠️ ADD
│   └── [Django] non-billing tenant can access (permission relaxed) ⚠️ ADD
└── Revenue aggregation
    └── [Django] TISSGuide sum for period ⚠️ ADD

S-069 Backend (full test suite)
├── Feature flag OFF → 403 ✅ (in plan)
├── DPA unsigned → 403 {"dpa_required": true} ✅ (in plan)
├── DPA row missing entirely → 403 (not AttributeError) ⚠️ ADD
├── Valid transcription > 10 chars → SOAP 4 fields non-empty ✅ (in plan)
├── Empty transcription → 400 ✅ (in plan)
├── Markdown-fenced JSON from Claude → parsed correctly ⚠️ ADD
├── Claude returns prose (not JSON) → 500 with degraded message ⚠️ ADD
├── Claude timeout → 503 "Serviço indisponível" ⚠️ ADD
├── Accept → ClinicalNote created with correct encounter + note_type="soap" ✅ (in plan)
├── AIScribeSession.accepted=True after accept ✅ (in plan)
├── Concurrent accept (double-click) → second returns 409 ⚠️ ADD
└── Cross-tenant IDOR: session from other tenant → 404 (not 200) ⚠️ ADD
```

**Test gaps requiring immediate spec addition:**

| Gap | Severity | Action |
|-----|----------|--------|
| OTP auto-submit on 6th digit | High | Add to S-067 frontend test spec |
| Polling interval cleared on unmount | High | Add to SafetyBadge test spec |
| DPA row missing → 403 not AttributeError | Critical | Add to S-069 backend tests |
| Markdown-fenced SOAP JSON | High | Add to S-069 backend tests |
| Claude timeout → 503 | High | Add to S-069 backend tests |
| Concurrent accept → 409 | High | Add to S-069 backend tests |
| Cross-tenant IDOR on scribe session | Critical | Add to S-069 backend tests |
| `period=` param for each value | Medium | Add to S-068 backend tests |
| Non-billing tenant can access analytics | Medium | Add to S-068 backend tests |

**Auto-decision:** All gaps accepted and added to test spec (P1: highest completeness).

---

## Section 4: Performance Review

**`OverviewView` with `?period=`:**
- `week` filter: `start_time__date__range=(week_start, today)` — existing index on `start_time` covers this. Query time ~10-30ms.
- `month` filter: same index. No new indexes needed.
- Revenue aggregation: `TISSGuide.objects.filter(appointment__start_time__date__range=...).aggregate(Sum("value"))` — adds one JOIN. Acceptable.

**S-069 scribe endpoint:**
- Synchronous LLM call: ~3-6s. Acceptable for voice dictation use case. No timeout set in the view layer — add `timeout=30` to the scribe view so long transcriptions don't hold a Django worker indefinitely. `ClaudeGateway` already has a timeout param, but the default is `settings.LLM_TIMEOUT` (verify this is set).
- `AIScribeSession.objects.create()` — single write, fast.
- No N+1 issues in the accept flow — `ClinicalNote.objects.create()` is a single write.

**S-067 safety polling:**
- Per Phase 1 Section 7: 5 polls × 10 drugs = 50 concurrent requests per prescription builder session. This is high. Add to spec: batch polling is preferred, but for Sprint 16, per-item polling is acceptable with a max of 5 polls per item and a max of 3 items polling simultaneously (queue the rest).

---

## Test Plan Artifact


Test plan written to: `~/.gstack/projects/tropeks-Vitali/tropeks-master-test-plan-sprint16-20260406.md`

---

## Phase 3 Completion Summary

| Section | Status | Issues Found |
|---------|--------|--------------|
| 0 (Scope Challenge) | ✅ | Approach B confirmed; 2 critical premises already resolved |
| Architecture | ⚠️ | ClaudeGateway pooling; AIScribeSession placement note |
| Code Quality | ⚠️ | AIDPAStatus None guard; SOAP fence stripping; period validation |
| Test Review | ⚠️ | 9 missing tests added to spec; test plan artifact written |
| Performance | ✅ | Indexes sufficient; 30s view timeout added to spec |
| Security | ⚠️ | Cross-tenant IDOR spec; raw_transcription PHI concern (pre-GA) |

**Phase 3 complete.** [subagent-only]. Claude subagent: 10 issues (4 critical, 3 high, 3 medium). Codex: N/A.
Consensus: 1/6 confirmed, 5 flagged → all addressed inline or deferred to TODOS.md.
Passing to Phase 3.5 check.

**Phase 3.5 (DX Review):** No developer-facing scope detected for Sprint 16 (no new SDK, no CLI tools, no API contracts changed for external consumers). Skipping. Log: "Phase 3.5 skipped — no DX scope."

Passing to Phase 4: Final Gate.

---

# TODOS.md Updates (collected from all phases)

See `docs/TODOS.md` for full deferred scope list.


---

# AUTOPLAN — Phase 4: Final Gate

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | autoplan | Scope & strategy | 1 | issues_open | 2 false premises corrected; 4 cherry-picks accepted |
| Codex Review | autoplan | Independent 2nd opinion | 0 | N/A (unavailable) | — |
| Eng Review | autoplan | Architecture & tests (required) | 1 | issues_open | 4 critical gaps fixed; 9 tests added |
| Design Review | autoplan | UI/UX gaps | 1 | clean | 5/10 → 8.6/10; 6 design decisions resolved |
| DX Review | skipped | No developer-facing scope | 0 | — | — |

**VERDICT:** PLAN REVIEWED — all critical issues resolved inline or deferred with rationale. Ready for implementation.


**STATUS: APPROVED 2026-04-06**
All review phases complete. Implementation ready.
Next: implement Sprint 16 per this reviewed plan.

