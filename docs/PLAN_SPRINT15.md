<!-- /autoplan restore point: /home/rcosta00/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260405-202027.md -->
# Sprint 15: Clinical AI Layer + MFA (v1.0.0)

**Theme:** First Phase 2 sprint — AI as a clinical co-pilot + security baseline for live pilot clinics.

**Version target:** v1.0.0 (semantic: first production-grade release)

**Stories:** S-062 through S-066

**Pre-req state (what v0.9.0 gives us):**
- `LLMGateway` abstract class + Claude/OpenAI implementations (S-030, Sprint 9)
- `AIPromptTemplate` + `AIUsageLog` models, Celery async LLM tasks
- `Prescription` + `PrescriptionItem` models (Sprint 5)
- `Encounter` model with CID-10 search (Sprint 4)
- `ClinicalNote` SOAP model (Sprint 5)
- `Allergy` model on Patient (Sprint 2)
- Feature flags per tenant (`FeatureFlag` model + middleware, Sprint 11)
- Celery beat + Redis in place (Sprint 13)
- Asaas PIX + email transactional infra (Sprint 14)

---

## S-062: Multi-Factor Authentication (TOTP)

**Goal:** Admin and medical staff protect their accounts with TOTP authenticator apps.
Healthcare data demands a second factor — LGPD + pilot clinic security baseline.

**Acceptance Criteria:**
- Superuser and `is_staff=True` users: MFA mandatory (login redirects to setup if not configured).
- All other users: MFA optional (can enroll from profile settings).
- Enrollment: scan QR code (TOTP secret displayed once), then confirm with 6-digit code.
- Backup codes: 8 single-use codes generated on enrollment; download as TXT.
- Login flow: email+password → TOTP prompt (separate step, JWT issued only after both pass).
- Recovery: superuser can disable MFA for any user from platform admin.
- Already-authenticated sessions: grace period 30 days before re-challenge.

**Backend:**
- `pip install django-otp pyotp qrcode[pil]`
- `TOTPDevice` model (from `django_otp.plugins.otp_totp`) — already in `django-otp`
- `MFARequiredMiddleware` — inspects JWT claims for `mfa_verified: true`; if user is staff/superuser and claim missing, return 403 with `{"mfa_required": true}` hint
- `POST /api/v1/auth/mfa/setup/` — generate secret, return QR URI + base32 secret
- `POST /api/v1/auth/mfa/verify/` — confirm TOTP code, mark device active, add `mfa_verified` to JWT, return backup codes (shown ONCE)
- `POST /api/v1/auth/mfa/login/` — second step after email+password; issues full JWT with `mfa_verified: true`
- `POST /api/v1/auth/mfa/disable/` — platform admin only
- Migration: `0007_totp_device.py`

**Frontend:**
- `app/(dashboard)/profile/security/page.tsx` — MFA enrollment: QR code display, confirmation input, backup codes download
- Login flow: after credential success with `mfa_required: true` in response → `/auth/mfa` step page
- `app/auth/mfa/page.tsx` — TOTP input (6-digit, auto-submit on 6th digit)
- Settings page shows MFA status badge (green check / grey "não configurado")

**Tests:**
- Login blocked without TOTP for staff users
- Backup code single-use enforcement
- Grace period respects 30-day window
- `mfa_required` middleware pass/fail

**Story Points:** 8

---

## S-063: AI Prescription Safety Net

**Goal:** When a doctor adds a drug to a prescription, the AI instantly checks:
1. Drug interactions with other active prescriptions for this patient
2. Dose range validation (alerts if prescribed dose is outside typical adult range)
3. Allergy cross-check against `Patient.allergy_set`
4. Contraindications for documented diagnoses in the current encounter

Uses existing `LLMGateway` (Claude API). Feature flag: `ai_prescription_safety`.

**Acceptance Criteria:**
- Adding any `PrescriptionItem` triggers a background safety check (async, non-blocking).
- If issues found, UI shows inline warning badge on the item row (⚠ yellow = caution, 🚫 red = contraindication).
- Doctor can acknowledge + override with reason (logged to AuditLog).
- No check fires if feature flag `ai_prescription_safety` is disabled for the tenant.
- Checks complete in < 5s (Claude Haiku — fast + cheap for structured checks).
- Responses cached 1h per (drug_combination_hash) to avoid redundant API calls.
- `AISafetyAlert` model tracks all alerts, override decisions, and outcomes.

**Backend:**
- `apps/emr/services/prescription_safety.py`:
  - `PrescriptionSafetyChecker.check(prescription_item, prescription)` → `SafetyResult`
  - Collects context: patient allergies, current prescription items, active diagnoses
  - Prompt: structured JSON response with `{alerts: [{type, severity, message, recommendation}]}`
  - Cache key: `sha256(drug_name + all_other_drugs_sorted + patient_allergy_names_sorted)`
- `AISafetyAlert` model: `prescription_item FK`, `alert_type`, `severity`, `message`, `acknowledged_by FK User`, `override_reason`, `created_at`
- `POST /api/v1/emr/prescriptions/{id}/items/{item_id}/safety-check/` — trigger check
- `POST /api/v1/emr/prescriptions/{id}/items/{item_id}/acknowledge-alert/` — accept + override
- Signal: `post_save` on `PrescriptionItem` → `check_prescription_safety.delay(item_id)`
- Celery task: `check_prescription_safety(item_id)` — runs check, saves `AISafetyAlert` if issues found, pushes WebSocket event

**Frontend:**
- `components/prescriptions/SafetyBadge.tsx` — inline badge on prescription item row
- `components/prescriptions/SafetyAlertModal.tsx` — expand alerts, acknowledge with reason
- Prescription builder polls `GET /api/v1/emr/prescriptions/{id}/items/{item_id}/safety-check/` for 10s
- Alert badge flashes amber during check, settles to green (clean) or yellow/red (issues)

**Tests:**
- Alert fired for known drug-drug interaction
- No alert for safe single-drug prescription
- Allergy cross-check fires for patient with documented allergy
- Cache hit prevents second LLM call for identical input
- Override saves to AuditLog with reason

**Story Points:** 13

---

## S-064: AI CID-10 Suggester

**Goal:** As the doctor types the encounter's clinical impression/diagnosis text, the AI suggests the top 3 most relevant CID-10 codes with a single click to apply.

Reuses the TUSS auto-coding pattern (S-031) but targets ICD-10 instead of TUSS.
Feature flag: `ai_cid10_suggest`.

**Acceptance Criteria:**
- In the encounter form, a text area "Hipótese diagnóstica" triggers suggestion after 1.5s debounce (min 20 chars).
- Returns top 3 CID-10 suggestions with code + description + confidence (%).
- All suggested codes are validated against the local CID-10 database (no hallucinated codes).
- One-click to apply suggestion → fills "CID-10 principal" field.
- `AICIDSuggestion` model tracks accepted/rejected outcomes for accuracy reporting.
- Responses cached 24h by content hash.

**Backend:**
- `apps/emr/services/cid10_suggester.py`:
  - `CID10Suggester.suggest(text: str) → list[CID10Suggestion]`
  - Prompt asks for JSON array `[{code, description, confidence}]`
  - Validates each suggested code against `CID10Code` model (reject any unknown codes)
  - Cache: `sha256(normalized_text)` → Redis, 24h TTL
- `AICIDSuggestion` model: `encounter FK`, `query_text`, `suggestions JSONB`, `accepted_code`, `created_at`
- `POST /api/v1/emr/encounters/{id}/cid10-suggest/` — returns suggestions
- `POST /api/v1/emr/encounters/{id}/cid10-accept/` — records accepted code

**Frontend:**
- `components/emr/CID10Suggest.tsx` — debounced inline suggestion panel (3 buttons with code + description)
- Wire into encounter edit form below the clinical impression textarea
- Suggestion panel shows loading spinner → 3 suggestion chips → click to accept

**Tests:**
- All returned codes exist in CID10Code table
- Hallucinated codes (not in DB) are filtered
- Cache hit avoids second LLM call
- Accepted suggestion recorded to `AICIDSuggestion`
- Feature flag disables endpoint (returns 403)

**Story Points:** 5

---

## S-065: Prescription PDF Export

**Goal:** Doctor or receptionist can download a professional, print-ready PDF of any prescription. Required for patients to take to a pharmacy. Uses WeasyPrint server-side.

**Acceptance Criteria:**
- `GET /api/v1/emr/prescriptions/{id}/pdf/` → returns `application/pdf` stream (or signed URL)
- PDF includes: clinic logo + name, doctor name + CRM number + specialty, patient name + date_of_birth, prescription date + validity (30 days), all prescription items with drug name + dosage + route + frequency + duration + instructions, digital hash footer (SHA-256 of prescription content), "DOCUMENTO GERADO PELO SISTEMA VITALI" watermark.
- Controlled substances (flag on `Drug.is_controlled`) render on a separate page with blue border ("Receituário Azul" format).
- Prescription must be signed before PDF can be generated (prevents unsigned prescriptions being printed).
- Font: Arial/Helvetica. Margins: 25mm. A4 paper.

**Backend:**
- `pip install weasyprint`
- `apps/emr/services/prescription_pdf.py`:
  - `PrescriptionPDFGenerator.generate(prescription) → bytes`
  - Jinja2 HTML template → WeasyPrint → PDF bytes
  - Digital hash: `sha256(prescription_id + all_item_data + signed_at.isoformat())`
- Templates: `apps/emr/templates/pdf/prescription.html` + `prescription_controlled.html`
- `GET /api/v1/emr/prescriptions/{id}/pdf/` — checks signed, generates PDF, returns as response with `Content-Disposition: attachment`
- Cache generated PDF in Redis (key: `prescription_pdf:{id}:{signed_at}`, 1h TTL)

**Frontend:**
- "Imprimir Receita" button in prescription detail → triggers `window.open(pdfUrl)`
- Also downloadable from patient timeline view

**Tests:**
- PDF generated for signed prescription
- 403 for unsigned prescription
- Controlled substance item → appears on separate controlled page
- PDF bytes are valid PDF (starts with `%PDF-`)
- Hash in footer matches recomputed hash

**Story Points:** 5

---

## S-066: Appointment Cancellation Waitlist

**Goal:** When a patient cancels, others on the waitlist are automatically notified via WhatsApp. Reduces no-show revenue loss and maximizes schedule utilization.

**Acceptance Criteria:**
- Patient (or receptionist on their behalf) can join waitlist for a specific professional + date range + time preference.
- When an appointment is cancelled for that professional, the first waitlisted patient is notified via WhatsApp (reuses WhatsApp module).
- Notification: "Uma vaga ficou disponível com [Dr. X] em [date] às [time]. Responda SIM para confirmar ou NÃO para ser removido da fila."
- If patient responds SIM within 30 minutes, appointment is booked automatically.
- If no response in 30 min, next waitlist entry is notified.
- Waitlist visible in receptionist appointment view (sidebar panel).
- Patients can cancel their waitlist entry at any time.

**Backend:**
- `WaitlistEntry` model: `patient FK`, `professional FK`, `preferred_date_from`, `preferred_date_to`, `preferred_time_start`, `preferred_time_end`, `notified_at`, `status (waiting/notified/booked/expired/cancelled)`, `created_at`
- Signal/task: `on_appointment_cancelled` → `notify_next_waitlist_entry.delay(professional_id, cancelled_slot)`
- `notify_next_waitlist_entry` Celery task:
  - Find first `WaitlistEntry` where professional matches + date range includes cancelled slot
  - Send WhatsApp message via `WhatsAppGateway`
  - Mark `status=notified`, set `notified_at=now()`
  - Schedule timeout task: `expire_waitlist_notification.apply_async(args=[entry_id], countdown=1800)`
- `expire_waitlist_notification` task: if entry still `notified` after 30 min → set `expired`, notify next entry
- WhatsApp response handler extended: `SIM`/`NÃO` from a notified entry → book or skip
- REST API:
  - `GET/POST /api/v1/emr/waitlist/` — list + create entries
  - `DELETE /api/v1/emr/waitlist/{id}/` — cancel entry

**Frontend:**
- `app/(dashboard)/appointments/waitlist/page.tsx` — waitlist management (receptionist view)
- "Entrar na fila de espera" button on unavailable slot in booking calendar
- Waitlist entries panel in appointment sidebar (status badges: waiting, notified, expired)

**Tests:**
- Cancellation triggers waitlist notification
- Expired timeout triggers next entry
- SIM response creates booking and cancels other entries for same slot
- NÃO response skips to next entry
- Waitlist entry scoped to correct professional + date range

**Story Points:** 8

---

## Technical Scope

### New models
- `TOTPDevice` (from `django-otp`, public schema)
- `AISafetyAlert` (tenant schema, `apps/emr/`)
- `AICIDSuggestion` (tenant schema, `apps/emr/`)
- `WaitlistEntry` (tenant schema, `apps/emr/`)

### New migrations
- `apps/core/migrations/0008_totp_device.py` (or handled by `django-otp` migration)
- `apps/emr/migrations/0009_ai_safety_alerts.py`
- `apps/emr/migrations/0010_cid10_suggestions.py`
- `apps/emr/migrations/0011_waitlist_entry.py`

### New dependencies
- `django-otp==1.4.x` + `qrcode[pil]`
- `pyotp`
- `weasyprint` (for PDF generation — requires OS-level Cairo/Pango, add to Dockerfile)

### New environment variables
```
MFA_GRACE_PERIOD_DAYS=30
PRESCRIPTION_PDF_CACHE_TTL=3600
```

### New feature flags (auto-seeded)
- `ai_prescription_safety` — on by default for new tenants
- `ai_cid10_suggest` — on by default for new tenants

### Celery beat additions
- `expire_waitlist_notifications`: every 5 minutes (check for stuck `notified` entries)

---

## Acceptance Criteria — Sprint-Level

All 5 stories pass at demo:
1. Staff user logs in, enrolls TOTP, logs out, logs back in with TOTP code. ✓
2. Doctor adds a drug the patient is allergic to → ⚠ badge appears within 5s. ✓
3. Doctor types "dor torácica intensa" in encounter → 3 CID-10 suggestions appear. ✓
4. Signed prescription → "Imprimir Receita" → PDF downloads with all required fields. ✓
5. Cancel appointment with waitlisted patient → WhatsApp notification arrives within 60s. ✓

---

## Dependencies & Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| WeasyPrint Cairo/Pango missing in Docker | High | Add `apt-get install -y libcairo2 libpango1.0-0` to Dockerfile |
| LLM latency > 5s for safety check | Medium | Use Claude Haiku (fast), cache aggressively, show optimistic "checking..." state |
| WhatsApp waitlist message misidentified as spam | Low | Use approved template messages via Evolution API |
| MFA lockout (user loses phone) | Medium | Backup codes + superuser disable endpoint |
| `django-otp` migration conflicts with billing_migrations MIGRATION_MODULES | Low | `django-otp` models go to public schema — separate from billing |

---

## Story Point Total: 39
**Estimated CC+gstack time:** ~90 min implementation

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | COMPLETE | 2 critical, 3 high, 3 medium. 5 auto-decided. Premise gate passed. |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | COMPLETE | 6 critical, 12 high, 16 medium, 11 low. Score: 4/10. |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | COMPLETE | 5 critical, 5 high, 7 medium, 4 low. Sprint health: 3.4/5. |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | UNAVAILABLE | OpenAI 401 — single-model findings only. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | SKIPPED | Not run in this pipeline. |

**VERDICT:** APPROVED. 18 decisions logged (13 mechanical, 3 eng, 2 user). 5 must-fix items before implementation. Sprint health: 3.4/5 → 4.2/5 after must-fixes applied.

---

# Phase 1: CEO Review

## PRE-REVIEW SYSTEM AUDIT

**Platform:** GitHub | **Base branch:** master | **Latest commit:** 59d1813

**Existing AI infrastructure:**
- `apps/ai/gateway.py`: `LLMGateway` (ABC) + `ClaudeGateway` — ready to reuse ✓
- `apps/ai/services.py`: `TUSSCoder` with 3-stage retrieval-hybrid pattern — exact template for CID10 Suggester ✓
- `apps/pharmacy/models.py`: `Drug.is_controlled` property — exists ✓
- **CID10Code model: DOES NOT EXIST** — S-064's "validate against CID10Code" is a fiction

**Hot files (last 14 days):** TODOS.md, settings/base.py, emr/models.py, billing/views.py — all Sprint 14, no conflicts.

**Design doc:** None found for this sprint. Standard review.

---

## 0A. Premise Challenge

**P1 (ASSUMED): Pilot clinics need AI before they need prescription PDF.**
False by priority order. Prescription PDF has been missing since Sprint 5 (S-015). If any real clinical prescription data exists in the system, doctors have been creating legally-void digital prescriptions since Sprint 5. S-065 unblocks the entire prescription workflow for real use. S-063 is differentiation on top of broken-but-unshipped basics.

**P2 (ASSUMED): TOTP MFA is the right auth upgrade for Brazilian clinic staff.**
Uncertain. TOTP requires authenticator apps — a non-trivial ask for clinic receptionists. Email OTP achieves the same security baseline with zero install friction. The plan doesn't evaluate this tradeoff.

**P3 (ASSUMED): LLM will reliably detect drug interactions from Brazilian free-text drug names.**
Not validated. `Drug.name` stores strings like "Dipirona Sódica 500mg (Medley)" — not DCB/ANVISA codes. The LLM has no structured drug interaction database; it uses training data only. Accuracy on Portuguese-language Brazilian drug names is unproven.

**P4 (ASSUMED): Sending patient allergy data + diagnoses to Claude API is LGPD-compliant.**
False by default. LGPD Art. 11 classifies health data as "dados sensíveis." Transmitting allergy + diagnosis data to an external API requires a third-party data processor agreement with Anthropic/OpenAI. None is documented. This is a compliance blocker for S-063.

**P5 (ASSUMED): CID10Code validation database exists.**
False. Confirmed by codebase search. There is no `CID10Code` model anywhere in the system. S-064's core acceptance criterion cannot be met as written.

---

## 0B. Existing Code Leverage Map

| Sub-problem | Existing code | Gap |
|-------------|--------------|-----|
| MFA enrollment + TOTP | `django-otp` (to install) | Backup codes, JWT claim injection |
| LLM call + caching | `apps/ai/services.py` TUSSCoder pattern | Drug safety prompt template |
| CID10 AI suggestion | `TUSSCoder` — near-identical pattern | `CID10Code` model (missing) |
| Prescription PDF | `apps/emr/models.py` Prescription + PrescriptionItem + signing | HTML template + WeasyPrint |
| Waitlist notifications | `apps/whatsapp/` WhatsApp gateway | `WaitlistEntry` model, SIM/NÃO disambiguation |
| Feature flag gating | `FeatureFlag` model + middleware | New flag names only |
| Allergy data | `Allergy` model on Patient | Already queryable |

Reuse score: HIGH. No new infra needed — everything builds on Sprint 5-14 foundations.

---

## 0C. Dream State Mapping

```
CURRENT STATE (v0.9.0)          THIS PLAN (v1.0.0)              12-MONTH IDEAL
─────────────────────────────   ─────────────────────────────   ────────────────────────────
Pilot clinic can:               + Staff secured with MFA         Full AI-assisted clinical
 - Manage patients ✓            + AI warns on drug interactions   workflow:
 - Schedule appts ✓             + AI suggests CID-10 codes        - AI scribe (voice→SOAP)
 - Create prescriptions ✓       + Prescriptions are printable      - Prescription safety at
   (but can't print them!)      + Cancellation waitlist           - Autonomous CID-10 coding
 - Bill via TISS ✓                                                - Smart scheduling (AI)
 - Receive PIX payments ✓                                        - Patient portal
 - Message via WhatsApp ✓                                        - DICOM/PACS viewer
                                                                  - BI dashboards
```

This plan moves in the right direction. The prescription gap (v0.9.0 state) is alarming — it should have been resolved in Sprint 5.

---

## 0C-bis. Implementation Alternatives

```
APPROACH A: "Clinical Completeness First" (current plan, reordered)
  Summary: Fix prescription PDF first, add AI features second. MFA optional-only.
  Effort:  L (39 SP as written)
  Risk:    Medium — LLM accuracy and LGPD unresolved
  Pros:    Delivers immediate clinical value (prescriptions)
           AI features differentiate vs. incumbents
           Waitlist reduces no-show revenue loss
  Cons:    LGPD blocker on S-063 not resolved
           CID10Code gap makes S-064 estimate wrong
  Reuses:  LLMGateway, TUSSCoder pattern, WhatsApp gateway

APPROACH B: "Pilot-Safe Subset"
  Summary: S-065 (prescription PDF) + S-062 MFA optional-enrollment + CID10Code DB only (no AI)
  Effort:  M (~18 SP)
  Risk:    Low — no LLM integration risks
  Pros:    Unblocks real clinical use immediately
           No LGPD exposure
           MFA infrastructure ready for mandatory enforcement later
  Cons:    No AI differentiation
           Waitlist + CID10 AI deferred to Sprint 16

APPROACH C: "AI-First with Legal Gate"
  Summary: Current plan but S-063 gated behind legal review completion; CID10Code DB as S-064 prerequisite
  Effort:  L (same SP but some stories blocked at merge)
  Risk:    Med-Low — builds the full vision, ships safe subset first
  Pros:    Legal review runs in parallel with S-064 infrastructure
           Full vision lands in 1 sprint
  Cons:    If legal review delays, S-063 blocks
           Complexity for a pilot sprint

RECOMMENDATION: Approach C — build the full vision but add legal gate on S-063 and
CID10Code DB step to S-064. This boils the lake (P1) while being explicit about the
compliance dependency (P5). Story points for S-064 → 13 (not 5).
```

---

## 0D. Selective Expansion Analysis

**Complexity check:** Plan touches ~25 files, introduces 4 new models/services — above the 8-file threshold. No scope reduction recommended (each story targets a distinct bottleneck). Challenge: S-063 should not ship until LGPD processor agreement exists.

**Minimum viable version:** S-065 alone unblocks real clinical use. S-062 MFA enrollment (no enforcement) adds security without lockout risk. That's the MVP of this sprint.

**Expansion opportunities (cherry-pick candidates):**

1. **Basic clinic analytics** (appointments today, week revenue, show rate) — HIGH value for pilot clinic owners; solves "pilot churn week 3" problem that CEO subagent identified. Effort: S. Auto-decision: DEFER to TODOS.md (P3 pragmatic — not in blast radius of this sprint's stories).

2. **CID10Code database import** — required by S-064; add as prerequisite task within S-064 scope. Auto-decision: IN SCOPE (P2 blast radius, P1 completeness).

3. **Email OTP as MFA alternative** — reduces pilot lockout risk. Auto-decision: DEFER to TODOS.md (P3 — TOTP is fine for MVP; email OTP is a nice-to-have).

4. **Prescription print-only mode (browser `window.print()`)** — simpler than WeasyPrint, zero OS dependencies. Auto-decision: TASTE DECISION (WeasyPrint gives better control; browser print is simpler; both valid — surface at gate).

5. **fpdf2/ReportLab instead of WeasyPrint** — pure Python, no OS deps. Auto-decision: TASTE DECISION (surface at gate).

---

## 0E. Temporal Interrogation

**HOUR 1:** S-065 is started. Developer installs WeasyPrint, discovers Cairo/Pango missing in dev Docker. Adds to Dockerfile. Builds prescription HTML template.

**HOUR 6:** S-065 PDF generates correctly. S-062 MFA enrollment flow works. TOTP QR scans correctly. JWT claim injection tested.

**HOUR 12:** S-063 service draft complete. Developer starts writing tests — realizes there's no test patient with known drug interactions in seed data. `seed_demo_data` must be updated. Also realizes allergy lookup requires joining across Patient → Allergy → PrescriptionItem → Drug — non-trivial query.

**HOUR 24:** S-064 starts. Developer opens `apps/ai/services.py`, copies TUSSCoder pattern. Reaches "validate against CID10Code model" — realizes the model doesn't exist. Full stop: must build CID10Code model + load DATASUS dataset first. This expands S-064 from 5 to 13+ points.

**HOUR 36:** S-066 WhatsApp waitlist integration. Developer realizes inbound "SIM" must be disambiguated from ongoing scheduling conversations. Opens `apps/whatsapp/` handlers — sees a flat message handler with no conversation-type scoping. Race condition risk identified.

**PLAN RISK:** Hours 24-36 are the danger zone. Both S-064 (missing CID10Code) and S-066 (WhatsApp disambiguation) will cause mid-sprint blockers if not addressed in planning now.

---

## CEO Dual Voices

**CODEX SAYS (CEO):** Codex unavailable — [single-model: Claude subagent only]

**CLAUDE SUBAGENT (CEO — strategic independence):**
10 findings across critical/high/medium severity. Top three:
1. CRITICAL: S-063 has LGPD processor gap + possible ANVISA SaMD classification requirement
2. CRITICAL: S-064 `CID10Code` model does not exist; estimate is wrong (5→13+ points)
3. HIGH: S-065 prescription PDF absence implies no real prescription printing for 9 sprints

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════════════════════
  Dimension                              Claude    Codex    Consensus
  ──────────────────────────────────────────────── ──────── ──────────────────
  1. Premises valid?                     PARTIAL   N/A     PARTIAL [subagent]
  2. Right problem to solve?             PARTIAL   N/A     PARTIAL [subagent]
  3. Scope calibration correct?          NO        N/A     AT RISK [subagent]
  4. Alternatives sufficiently explored? PARTIAL   N/A     PARTIAL [subagent]
  5. Competitive/market risks covered?   PARTIAL   N/A     PARTIAL [subagent]
  6. 6-month trajectory sound?           PARTIAL   N/A     PARTIAL [subagent]
═══════════════════════════════════════════════════════════════════════════════
CONFIRMED = both agree. N/A = Codex unavailable. [subagent] = single-voice finding.
```

---

## Section 1: Strategic Alignment

The sprint correctly targets Phase 2 features. Prescription PDF (S-065) is the highest-ROI story. AI Safety Net (S-063) is the strongest competitive differentiator if the LGPD and accuracy issues are resolved. CID-10 AI (S-064) reuses the TUSSCoder pattern exactly. MFA (S-062) is the right security story but should be optional during pilot. Waitlist (S-066) solves a real problem but may be premature for a pilot clinic that hasn't yet proven high schedule utilization.

**Auto-decided:** Retain all 5 stories. Fix scope of S-062 (optional enforcement), S-064 (add CID10Code DB step), S-063 (add legal gate + disclaimer).

## Section 2: Error & Rescue Registry

| Error | Source | Trigger | Catch | User sees | Tested? |
|-------|--------|---------|-------|-----------|---------|
| TOTP code wrong 3× | S-062 MFA login | User miskeys | `MFARequiredMiddleware` → 403 | "Código inválido. Use os códigos de backup." | Needed |
| TOTP device deleted (phone lost) | S-062 | User logs in | superuser disable endpoint | "Contate o administrador" | Needed |
| LLM API timeout on safety check | S-063 | Celery task | try/catch → `AISafetyAlert.status=error` | No badge (silent fail) — badge only on confirmed issues | Needed |
| LLM returns malformed JSON | S-063 | Celery task | JSON parse error → log + skip | No badge | Needed |
| CID10Code empty/not seeded | S-064 | CID10 suggest call | `CID10Code.objects.filter().exists()` check | "Sugestão indisponível" | Needed |
| WeasyPrint Cairo missing | S-065 | First PDF request | ImportError / subprocess error | 500 → "PDF indisponível" | Needed (Docker check) |
| Waitlist SIM from wrong conversation | S-066 | WhatsApp inbound | WaitlistEntry state check | Ignored (no active `notified` entry) | Needed |
| Duplicate waitlist notification | S-066 | Race condition | `select_for_update()` on entry | First notification wins | Needed |

## Section 3: Failure Modes Registry

| Mode | Probability | Impact | Detection | Mitigation |
|------|-------------|--------|-----------|------------|
| AI Safety Net gives false negative (misses real interaction) | Med | CRITICAL (patient safety) | No detection once overridden | UI disclaimer mandatory; accuracy baseline test suite |
| CID10 AI suggests hallucinated code (no DB) | High (no validation) | High (wrong billing) | No detection without CID10Code table | Build CID10Code table first |
| MFA locks out pilot clinic staff | Low-Med | High (churn event) | Support call | Make enforcement optional |
| WeasyPrint breaks in Docker | Med | High (no prescriptions) | First PDF attempt | CI test that generates a PDF in Docker |
| WhatsApp waitlist double-books | Low-Med | High (patient complaint) | `select_for_update` | Add slot re-check before confirmation |
| LGPD violation (allergy data to LLM) | High (if no DPA) | CRITICAL (regulatory) | ANPD audit | DPA with Anthropic/OpenAI before S-063 ships |

## Section 4: NOT In Scope

- Basic clinic analytics dashboard (daily appointments, weekly revenue, show rate) — DEFER to TODOS.md
- Email OTP as MFA alternative — DEFER to TODOS.md
- SMS/WhatsApp OTP — Phase 3
- ANVISA drug interaction database integration — too complex for this sprint; use LLM only
- Patient portal (read-only) — Phase 3
- AI Scribe (voice to SOAP) — Phase 3

## Section 5: What Already Exists

| S-064/S-063 need | Existing code | Location |
|-----------------|---------------|----------|
| LLM API call + cache | `TUSSCoder` | `apps/ai/services.py:152+` |
| Claude gateway | `ClaudeGateway` | `apps/ai/gateway.py:33` |
| Allergy model | `Allergy` | `apps/emr/models.py:117` |
| Drug model | `Drug` + `is_controlled` | `apps/pharmacy/models.py:18,60` |
| PrescriptionItem | `PrescriptionItem` | `apps/emr/models.py:419` |
| WhatsApp send | `WhatsAppGateway` | `apps/whatsapp/` |
| Feature flags | `FeatureFlag` | `apps/core/models.py` |
| Celery + beat | Already configured | `vitali/celery.py` |

## Section 6: Dream State Delta

This plan leaves us at ~70% of the 12-month ideal. Missing: basic analytics, voice scribe, patient portal, DICOM/PACS, smart scheduling. These are correctly in Phase 2-3.

## Section 7: Security Review

S-063: **CRITICAL** — LGPD processor agreement required before transmitting patient health data to external LLM.
S-062: MFA adds meaningful auth security. Backup code one-use enforcement is correct.
S-066: WhatsApp SIM/NÃO confirmation must re-check slot availability before booking to prevent race.

## Section 8: Observability

Plan has `AISafetyAlert` and `AICIDSuggestion` models for tracking. Missing: Celery task failure metrics for LLM calls, PDF generation latency, MFA enrollment rate per tenant. Add to TODOS.md.

## Sections 9-10: Dependencies, Timeline

Unblocked. All deps exist or are created in this sprint. No external API dependencies beyond Claude API (already integrated).

## CEO Completion Summary

| Category | Count | Notes |
|----------|-------|-------|
| Stories reviewed | 5 | S-062 through S-066 |
| Critical issues | 2 | S-063 LGPD, S-064 missing CID10Code |
| High issues | 3 | Sprint mix, premises, S-065 gap |
| Medium issues | 3 | S-062 scope, S-066 timing, alternatives |
| Auto-decided | 5 | Scope fixes, reordering, CID10Code addition |
| User Challenges | 1 | S-063 LGPD (ship as on-by-default?) |
| Taste Decisions | 2 | PDF library choice (WeasyPrint vs fpdf2), S-066 vs analytics |
| Deferred to TODOS | 3 | Analytics, email OTP, observability metrics |

**CEO PHASE COMPLETE.**

---

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|---------------|-----------|-----------|---------|
| 1 | CEO | S-062: MFA enforcement optional during pilot (no 30-day mandatory timer) | Mechanical | P3 Pragmatic | Lockout at pilot clinic = churn event; compliance infrastructure still built | Mandatory enforcement |
| 2 | CEO | S-064: add CID10Code model + DATASUS import as prerequisite task | Mechanical | P1 Completeness | Plan validation gate cannot be built without the model | Skip validation |
| 3 | CEO | S-064: story points revised 5→13 to reflect actual scope | Mechanical | P5 Explicit | 5-point estimate was fiction; hidden prerequisite changes scope | Keep 5-point estimate |
| 4 | CEO | S-063: add LGPD disclaimer + DPA requirement gate before default-on | User Challenge | N/A | Both analyst and subagent identify LGPD exposure; legal review required | Ship S-063 as-is |
| 5 | CEO | PDF library: WeasyPrint vs fpdf2/browser-print | Taste | — | Both viable; WeasyPrint gives more control; fpdf2 is simpler | — |
| 6 | CEO | S-066 vs analytics story | Taste | — | Waitlist solves real problem; analytics solves retention risk; user decides | — |
| 7 | CEO | CID10Code database: add to public schema (like TUSSCode pattern) | Mechanical | P4 DRY | TUSSCode precedent; public schema allows tenant-shared lookup | Tenant-per-schema |
| 8 | Design | S-062: Show backup codes after TOTP verified, not before | Mechanical | P1 Completeness | Showing codes before 2nd-factor verified defeats the security guarantee | Show codes immediately on generation |
| 9 | Design | S-063: Add required override reason for red-severity (contraindication) items | Mechanical | P5 Explicit | Silent acknowledgment of contraindication is unsafe; reason field must be non-blank for severity=red | Optional reason for all severities |
| 10 | Design | S-063: Add AI disclaimer text inside SafetyAlertModal (not just privacy policy link) | Mechanical | P5 Explicit | "This check is AI-assisted. Always apply clinical judgment." must be visible at point of override | External link only |
| 11 | Design | S-062: Add dedicated MFA lockout/lost-phone UI path (not just "contact admin" toast) | Mechanical | P3 Pragmatic | Pilot clinics need self-service or clear escalation path for MFA recovery | Generic error message |
| 12 | Design | S-066: Specify waitlist entry form fields (date range, time preference, professional) | Mechanical | P1 Completeness | Form is entirely unspecified in plan — must define fields before implementation | Ad-hoc implementation |
| 13 | Eng | S-063: Use transaction.on_commit() for Celery dispatch in post_save signal | Mechanical | P5 Explicit | Race condition: task fires before DB commit, reads stale data. on_commit() is the standard Django pattern | direct delay() in post_save |
| 14 | Eng | S-062: Do NOT use django-otp package — build custom TOTPDevice model with pyotp | Mechanical | P3 Pragmatic | Eliminates migration sequencing conflict; 50-line model is all that's needed | Add django-otp to TENANT_APPS |
| 15 | Eng | S-064: All AI cache keys must include schema_name: ai:{feature}:{schema_name}:{digest} | Mechanical | P5 Explicit | Cross-tenant cache sharing is a LGPD violation; schema isolation is mandatory | Global cache keys without tenant scope |
| 16 | Eng | S-065: WeasyPrint vs reportlab (pure Python, no OS deps) | Taste | — | WeasyPrint: best HTML/CSS control, high Docker risk. reportlab: simpler, Python-only. Both viable. | — |
| 17 | Gate | S-065: WeasyPrint chosen for HTML/Jinja2 template approach | User Decision | T-1 | User selected WeasyPrint. Add Cairo/Pango to Dockerfile. Templates: prescription.html + prescription_controlled.html | reportlab |
| 18 | Gate | S-066: Keep Waitlist (not swapped for Analytics) | User Decision | T-2 | User confirmed Waitlist. Analytics deferred to TODOS.md (still valid for pilot churn mitigation). | Analytics story |

---

# Phase 2: Design Review

**Subagent:** Claude design subagent (Codex designer unavailable — 401 on OpenAI key)
**Methodology:** Plan-level wireframe analysis + interaction flow audit + accessibility spot-check
**Score: 4/10 design completeness**

---

## Design Litmus Scorecard

| Criterion | Score | Notes |
|-----------|-------|-------|
| Information architecture | 5/10 | Core flows sketched; secondary states missing |
| Interaction states (loading/error/empty) | 3/10 | Most empty/error states unspecified |
| Accessibility (WCAG 2.1 AA) | 2/10 | Color-only encoding on severity badges; no alt-text strategy |
| Copy / microcopy | 3/10 | Portuguese strings implied but not written; AI disclaimer missing |
| Mobile responsiveness | 4/10 | Prescription PDF and MFA pages not specified for mobile |
| Component reuse | 6/10 | `SafetyBadge` + `SafetyAlertModal` match existing pattern |
| Security UX | 4/10 | MFA backup code exposure timing is wrong |
| **Overall** | **4/10** | Critical gaps in 6 of 7 criteria |

---

## Design Findings

### CRITICAL (6 items — block implementation)

**D-01: Backup codes exposed before TOTP verified**
- `app/(dashboard)/profile/security/page.tsx` plan: QR code display → confirmation input → backup codes
- Problem: backup codes are shown in the same step as TOTP confirmation — if the user never completes TOTP setup (closes browser mid-flow), they have backup codes for a device that's never been activated.
- Fix: Two-phase enrollment. Phase 1: QR + TOTP confirm → device marked active. Phase 2: backup codes generated and displayed. Codes appear only after device is verified.
- Component: `MFAEnrollStep1.tsx` (QR + confirm) → `MFAEnrollStep2.tsx` (backup codes only after verified).

**D-11: Silent fail state for LLM timeout on S-063**
- Plan says "badge flashes amber during check, settles to green or yellow/red"
- No state specified for: timeout (> 5s), API error, JSON parse fail, feature flag off
- Users see an amber badge forever on LLM error — looks like "checking" indefinitely
- Fix: Add explicit `error` badge state: grey shield + "Verificação indisponível" tooltip. Set badge to `error` after 10s or on Celery task failure. Never leave badge in perpetual amber.

**D-12: Color-only severity encoding on SafetyBadge**
- Plan: `⚠ yellow = caution, 🚫 red = contraindication`
- WCAG 1.4.1: Information must not be conveyed by color alone
- ~8% of male users have red-green color blindness; yellow/red is indistinguishable for deuteranopia
- Fix: Each severity state needs a distinct icon: warning triangle (⚠) for caution, prohibited circle (🚫) for contraindication, checkmark (✓) for clean, spinner for checking, shield-x for error. Icon shape, not color, must carry the meaning.

**D-18: No AI disclaimer inside SafetyAlertModal**
- S-063 plan: modal shows alerts + acknowledge + override reason
- Missing: any text telling the doctor this is AI-generated and may be wrong
- ANVISA SaMD risk: without a disclaimer, the system could be construed as providing a clinical recommendation, not a decision-support tool
- Required copy (inside modal footer, every time): *"Esta verificação é assistida por IA e pode conter erros. Sempre aplique julgamento clínico. Vitali não se responsabiliza por decisões baseadas exclusivamente nesta análise."*

**D-19: Required vs optional override reason not specified by severity**
- Plan says "Doctor can acknowledge + override with reason (logged to AuditLog)"
- No spec for when reason is required vs optional
- Safe UX: severity=caution (yellow) → reason optional; severity=contraindication (red) → reason required (non-blank, min 10 chars)
- Implement: `SafetyAlertModal` shows required asterisk + validation on reason field when severity=red

**D-35: Waitlist entry form entirely unspecified**
- `app/(dashboard)/appointments/waitlist/page.tsx` is mentioned but no field list exists
- Minimum required fields: Professional (dropdown), Preferred date from/to (date pickers), Preferred time window (morning/afternoon/any), Patient (auto-filled if logged in), Contact via WhatsApp (confirmed phone number)
- Edge cases: what if the preferred date range has passed? what if the professional has no future availability? Both need empty state copy.

---

### HIGH (12 items)

**D-02: MFA QR code accessibility** — QR images must have alt text + manual entry code displayed as fallback for screen readers and users with camera access issues. Add `<code>` element below QR image showing the base32 secret.

**D-03: Grace period countdown missing from UI** — 30-day grace period is implemented but never surfaced. Users will be surprised when they're suddenly challenged for TOTP. Add a "MFA required in X days" banner on the dashboard if grace period is active.

**D-04: Backup codes download UX** — "Download as TXT" is insufficient. Users on mobile can't download. Add: copy-to-clipboard button + option to display codes in-browser for screenshot. Each code should be formatted in pairs (e.g. `AB12-CD34`) for readability.

**D-05: S-064 debounce feedback** — 1.5s debounce with no feedback means the user types, nothing happens for 1.5s, then suggestions appear. Add a subtle "searching..." microtext below the field that appears after 500ms of typing (before debounce fires). Prevents "is this working?" confusion.

**D-06: S-064 suggestion chip design** — Plan says "3 suggestion chips" but doesn't specify what to show on rejection. If user clicks all 3 chips but none are right, what happens? Add a "None match — enter manually" escape hatch that dismisses the panel.

**D-07: S-065 print button placement** — "Imprimir Receita" button in prescription detail — which prescription detail? The `/prescriptions/{id}/` page or the encounter's inline prescription section? Both views exist. Specify which.

**D-08: S-065 unsigned prescription CTA** — User clicks "Imprimir Receita" on an unsigned prescription → 403. Show a clear pre-check: disable the button with tooltip "Assine a receita antes de imprimir" rather than letting the request fail.

**D-09: S-066 30-min timer visibility** — Patient is notified via WhatsApp and has 30 min to respond. No way for the receptionist to see the countdown. Add a "expires in X min" badge on notified entries in the waitlist sidebar.

**D-10: S-066 NÃO response copy** — "Responda NÃO para ser removido da fila" — does this remove the patient from the entire waitlist or just this notification? If just this slot, they stay on the waitlist. Copy must be explicit: "Responda NÃO para ignorar esta vaga (você permanece na fila de espera)."

**D-13: SafetyAlertModal loading state** — Modal is opened by doctor; check is async. What does the doctor see if they open the prescription before the Celery task completes? Show a loading state inside the modal with spinner + "Verificando..." rather than an empty modal.

**D-14: MFA `/auth/mfa` page — error differentiation** — Wrong code vs expired code (TOTP is time-synced, can expire in 30s) vs used backup code are different errors. All should have distinct error copy.

**D-15: S-062 platform admin disable MFA flow** — `POST /api/v1/auth/mfa/disable/` exists but no admin UI is specified. Platform admin needs a simple "Disable MFA for user" action in the platform monitor page (already exists at `/platform/monitor`).

---

### MEDIUM (16 items)

**D-16:** S-064 suggestion panel — keyboard navigation (arrow keys to navigate chips, Enter to select) not specified.
**D-17:** S-062 enrollment page — what happens if user navigates away mid-enrollment? Incomplete device should be purged. Add `beforeunload` warning or server-side session expiry for incomplete TOTPDevice.
**D-20:** S-065 PDF — clinic logo is referenced but no upload mechanism exists for it. Add fallback: clinic name as text header if no logo uploaded.
**D-21:** S-065 PDF — "DOCUMENTO GERADO PELO SISTEMA VITALI" watermark — light enough to not interfere with readability but dark enough to be visible when photocopied. Specify opacity: 0.08 (10% grey).
**D-22:** S-066 waitlist sidebar — what does the receptionist see when the waitlist is empty? "Nenhum paciente na fila de espera" empty state with a CTA to add a patient.
**D-23:** SafetyBadge flashing animation — amber flashing while checking could be distracting in a prescription list with multiple items. Use a static spinner icon rather than a flashing amber badge.
**D-24:** S-062 backup codes — user must acknowledge they've saved the codes before continuing. Add a checkbox: "Guardei meus códigos de backup" before dismissing the codes screen.
**D-25:** S-064 — minimum 20 chars for debounce. Users who type exactly 20 chars won't see suggestions until they type more. Consider 15-char threshold or show "Keep typing..." microcopy at < 20 chars.
**D-26:** S-063 — cache invalidation when allergies are updated. If a patient's allergy is added after a safety check was cached, the cached result is stale. Cache key must include patient allergy set hash.
**D-27:** S-065 — prescription validity period (30 days) shown in PDF. Does the doctor see this before printing? Add validity date to the prescription detail page.
**D-28:** S-066 — if the same patient is in the waitlist for the same slot and is notified, then cancels their waitlist entry during the 30-min window, the system might still try to book them. Confirm cancellation during `notified` state should cancel the pending booking intent.
**D-29:** S-062 — TOTP app recommendations for Brazilian users. Many users won't know what "authenticator app" means. Add a help tooltip: "Use Google Authenticator, Authy, ou Microsoft Authenticator" with app store links.
**D-30:** S-063 — alert deduplication. If the same drug is added twice to a prescription (duplicated by accident), two safety checks fire. Should show one combined alert, not two.
**D-31:** S-064 — suggestion chips need confidence % display. Plan says "top 3 CID-10 suggestions with code + description + confidence (%)". Show confidence as a subtle percentage below the code description, not as the primary label.
**D-32:** S-065 — "Receituário Azul" (controlled substance page) must have a blue border per ANVISA format. Specify border: `2px solid #1565C0`. Standard A4 controlled substance form layout.
**D-33:** S-066 — waitlist re-entry after booking expires should be allowed with a single tap. If a patient's booking fails (slot taken by someone else simultaneously), they should be returned to the waitlist automatically, not have to re-enter.

---

### LOW (11 items)

**D-34:** MFA enrollment — consider progressive disclosure. Don't show TOTP explanation upfront; show a "What is this?" expandable section.
**D-36:** PDF footer — digital hash shown as raw SHA-256 hex is 64 chars and unreadable. Show first 12 chars with a "Verificar autenticidade" link to a validation page.
**D-37:** S-064 — suggestion panel should disappear on click-away, not require an explicit dismiss button.
**D-38:** SafetyBadge — add `title` attribute to badge elements for screen-reader context ("Verificação limpa", "Aviso de interação", "Contraindicação detectada").
**D-39:** S-063 — acknowledged alerts should be visually distinct from unacknowledged (strikethrough or grey-out), not removed from the modal. Doctor should see their overrides.
**D-40:** S-062 — QR code size. Minimum 200×200px for reliable scanning from standard desk setups.
**D-41:** S-065 — prescription PDF font. Arial is a Windows font; Linux/Docker may not have it. Use Liberation Sans (metrically equivalent, freely licensed, available in Ubuntu). Add to Dockerfile.
**D-42:** S-066 — Waitlist entry status badge colors: waiting=blue, notified=amber, booked=green, expired=grey, cancelled=red. Consistent with appointment status badges in Sprint 14.
**D-43:** S-063 — batch safety check for existing prescription items on modal open. If a doctor opens an existing prescription, all items should show their cached safety states, not just newly added items.
**D-44:** S-064 — "Hipótese diagnóstica" textarea label should include a hint: "(Digite para receber sugestões de CID-10)".
**D-45:** S-066 — WhatsApp notification copy. "Responda SIM para confirmar" — use uppercase SIM/NÃO consistently. Lowercase variations (sim, não) must be accepted by the inbound handler.

---

## Design ASCII Wireframes

### S-062: MFA Enrollment — Two-Phase Flow

```
Phase 1: Scan & Verify                Phase 2: Save Backup Codes
┌─────────────────────────────┐      ┌─────────────────────────────┐
│ Configurar Autenticação MFA │      │  Códigos de Backup ✓        │
├─────────────────────────────┤      ├─────────────────────────────┤
│  1. Escaneie o QR code:     │      │  ⚠ Guarde estes códigos    │
│  ┌─────────────────────┐   │      │  em local seguro. Cada     │
│  │  ▄▄▄▄▄  ▄▄▄▄▄▄▄▄  │   │      │  código só pode ser usado  │
│  │  █   █  █ ▀█▀ █  │   │      │  uma vez.                  │
│  │  █▄▄▄█  █ █▄█ █  │   │      │                             │
│  │  ▀▀▀▀▀  ▀▀▀▀▀▀▀▀  │   │      │  AB12-CD34  EF56-GH78     │
│  │  [200×200 QR code]  │   │      │  IJ90-KL12  MN34-OP56     │
│  └─────────────────────┘   │      │  QR78-ST90  UV12-WX34     │
│                             │      │  YZ56-AB78  CD90-EF12     │
│  Ou insira manualmente:    │      │                             │
│  [JBSWY3DPEHPK3PXP...]    │      │  [📋 Copiar]  [⬇ Baixar]  │
│  [? Use Google Authenticator│      │                             │
│   Authy, ou MS Authenticator│      │  ☐ Guardei meus códigos   │
│                             │      │    de backup               │
│  2. Digite o código gerado: │      │                             │
│  [  _  _  _    _  _  _  ] │      │  [Concluir Configuração →]  │
│                             │      └─────────────────────────────┘
│  [← Cancelar] [Verificar →]│
└─────────────────────────────┘

Grace period banner (dashboard):
┌──────────────────────────────────────────────────────────────┐
│ 🔒 Configure a autenticação MFA em 28 dias para manter      │
│ acesso. [Configurar agora]                     [Lembrar depois]│
└──────────────────────────────────────────────────────────────┘
```

### S-063: AI Safety Badge + Alert Modal

```
Prescription Item Row:
┌────────────────────────────────────────────────────────────────────┐
│ Drug Name              Dose        Route    Freq    Duration  [⚠]  │
├────────────────────────────────────────────────────────────────────┤
│ Warfarina 5mg          1 comp.     VO       1×/dia  30 dias   [🚫] │◄─ red badge
│ Dipirona Sódica 500mg  1 comp.     VO       3×/dia  7 dias    [⚠]  │◄─ yellow badge
│ Amoxicilina 500mg      1 caps.     VO       3×/dia  7 dias    [✓]  │◄─ green badge
│ Omeprazol 20mg         1 caps.     VO       1×/dia  30 dias   [⟳]  │◄─ spinner (checking)
└────────────────────────────────────────────────────────────────────┘
                                            Badges: shape + color (not color alone)

SafetyAlertModal (Warfarina — red):
┌─────────────────────────────────────────────────────────┐
│  🚫 Verificação de Segurança — Warfarina 5mg           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ CONTRAINDICAÇÃO ────────────────────────────────┐  │
│  │ 🚫 Interação grave: Warfarina + AAS 100mg        │  │
│  │ Risco aumentado de sangramento. Revisão necessária│  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─ AVISO ──────────────────────────────────────────┐  │
│  │ ⚠ Paciente relata alergia a anticoagulantes     │  │
│  │ Confirmar histórico antes de prescrever          │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  Justificativa para prescrição (obrigatório*):         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ [Digite a justificativa clínica...           ]   │  │
│  └──────────────────────────────────────────────────┘  │
│  * Mínimo 10 caracteres para contraindicações          │
│                                                         │
│  [Cancelar]              [Confirmar e Registrar →]     │
│                                                         │
│  ────────────────────────────────────────────────────  │
│  ℹ Esta verificação é assistida por IA e pode conter  │
│  erros. Sempre aplique julgamento clínico.            │
└─────────────────────────────────────────────────────────┘

Badge states:
  [⟳] spinner  = checking (Celery task in progress, < 10s)
  [✓] green    = clean (no issues)
  [⚠] yellow   = caution (warning, override optional)
  [🚫] red     = contraindication (override required + reason)
  [?] grey     = error (LLM timeout / unavailable)
```

### S-066: Waitlist Entry Form

```
┌────────────────────────────────────┐
│  Entrar na Fila de Espera          │
├────────────────────────────────────┤
│  Profissional *                    │
│  [Selecionar médico...     ▼]      │
│                                    │
│  Período preferido *               │
│  De [__/__/____] Até [__/__/____]  │
│                                    │
│  Horário preferido                 │
│  ○ Manhã  ○ Tarde  ○ Qualquer      │
│                                    │
│  Contato WhatsApp *                │
│  [+55 11 99999-9999      ]         │
│                                    │
│  [Cancelar]   [Entrar na Fila →]   │
└────────────────────────────────────┘

Waitlist sidebar (receptionist view):
┌──────────────────────────────────────┐
│ Fila de Espera (3)        [+ Adicionar]│
├──────────────────────────────────────┤
│ Maria Souza                          │
│ Dr. Silva · Manhã · 07-12 abr        │
│ [🔵 Aguardando]                      │
├──────────────────────────────────────┤
│ João Santos                          │
│ Dr. Silva · Qualquer · 07-15 abr     │
│ [🟡 Notificado] expira em 18 min     │
├──────────────────────────────────────┤
│ Ana Lima                             │
│ Dr. Pereira · Tarde · 10-20 abr      │
│ [🔵 Aguardando]                      │
└──────────────────────────────────────┘
```

---

## Design Dual Voices

**CODEX (Design):** Unavailable — OpenAI key 401.
**CLAUDE SUBAGENT (Design):** 45 findings (6 critical, 12 high, 16 medium, 11 low). Score 4/10.

```
DESIGN DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════════════════
  Dimension                              Claude    Codex    Consensus
  ──────────────────────────────────────────────── ──────── ──────────────────
  1. Interaction states complete?        NO        N/A      INCOMPLETE [single]
  2. Accessibility (WCAG 2.1 AA)?        NO        N/A      FAILS [single]
  3. Copy/microcopy specified?           NO        N/A      MISSING [single]
  4. Security UX sound?                  PARTIAL   N/A      AT RISK [single]
  5. Component patterns consistent?      PARTIAL   N/A      PARTIAL [single]
  6. Mobile considered?                  NO        N/A      NOT SPECIFIED [single]
═══════════════════════════════════════════════════════════════════════════
N/A = Codex unavailable. [single] = single-voice finding only.
```

---

**Phase 2 complete.** Claude design subagent: 45 issues (6 critical, 12 high, 16 medium, 11 low). Codex: unavailable. Consensus: 6/6 dimensions have gaps, 5 new decisions added to audit trail. Passing to Phase 3.

---

# Phase 3: Engineering Review

**Subagent:** Claude engineering subagent (Codex unavailable)
**Methodology:** Architecture analysis, test plan generation, migration safety audit, dependency risk
**Overall sprint health: 3.4/5 — READY WITH CAVEATS (5 critical fixes required)**

---

## Architecture Data Flow — S-063 (Prescription Safety Check)

```
HTTP POST /emr/prescriptions/{id}/items/
           │
           ▼
  PrescriptionItem.save() ◄── inside DB transaction
           │
           ▼
  Django post_save signal
  (WARNING: fires inside uncommitted txn)
           │
           ▼
  REQUIRED PATTERN: transaction.on_commit(
    lambda: check_prescription_safety.delay(item_id)
  )
           │
           ▼ (after commit)
  Celery: check_prescription_safety(item_id)
           │
    ┌──────┤
    │      ▼
    │  Feature flag: ai_prescription_safety
    │  (default OFF, requires Anthropic DPA)
    │  IF DISABLED → mark badge=disabled, return
    │      │
    │      ▼
    │  Redis cache: sha256(drug_name + drugs_sorted + allergy_names_sorted + schema_name)
    │  IF HIT → return cached result
    │      │
    │      ▼
    │  LLMGateway (ClaudeGateway / claude-haiku-4-5-20251001)
    │  Timeout: 10s, max_tokens: 256
    │  Returns: {alerts: [{type, severity, message, recommendation}]}
    │      │
    │      ▼
    │  Create AISafetyAlert (if issues found)
    │  Cache result (1h TTL)
    │      │
    └──────┤
           ▼
  WebSocket emit → 'safety_check_complete'
  Room: prescription:{prescription_id}
  Payload: {item_id, is_safe, severity, alert_reason}
           │
           ▼
  React: useWebSocket('prescription:{id}')
  Badge: [⟳]→[✓]/[⚠]/[🚫]/[?]
```

---

## Test Plan

| Story | Test | Type | Class | Why Load-Bearing |
|-------|------|------|-------|------------------|
| S-062 | `test_setup_generates_valid_qr_code` — pyotp device + qrcode generation works, secret scannable | Unit | TestCase | QR broken = no MFA for anyone |
| S-062 | `test_verify_totp_drift_windows` — T-1, T, T+1 all pass; T+2 fails | Unit | TestCase | Drift causes support tickets |
| S-062 | `test_jwt_mfa_verified_claim_present_after_login` — JWT has `mfa_verified=true` only after TOTP step | Integration | APITestCase | Claim missing = anyone bypasses MFA |
| S-063 | `test_safety_check_fires_via_on_commit_not_post_save` — Celery task NOT called before transaction commits | Integration | TenantTestCase | Race condition if wrong pattern |
| S-063 | `test_cache_prevents_duplicate_llm_calls` — same input twice → 1 LLM call | Integration | TenantTestCase | ~€20/day waste if cache broken |
| S-063 | `test_allergy_crosscheck_fires_for_patient_with_known_allergy` — alert created for drug patient is allergic to | Integration | TenantTestCase | Core feature correctness |
| S-064 | `test_cid10code_queries_public_schema` — `.using('public')` returns data from TenantTestCase | Integration | TenantTestCase | Silent fail = zero suggestions for all tenants |
| S-064 | `test_cache_key_includes_schema_name` — tenant A and B don't share cached CID-10 results | Unit | TestCase | Cross-tenant data leak = LGPD violation |
| S-064 | `test_accept_updates_encounter_cid10_field` — POST /cid10-accept/ sets Encounter.diagnosis_cid10 | Integration | APITestCase | Accept is the UX; broken = can't apply suggestions |
| S-065 | `test_pdf_requires_signed_prescription` — 403 if signed_at is null | Integration | APITestCase | Unsigned PDF is invalid (CFM rule) |
| S-065 | `test_controlled_substance_on_separate_page` — Drug.is_controlled=True → appears on Receituário Azul page | Integration | TenantTestCase | Regulatory requirement (Anvisa) |
| S-065 | `test_pdf_bytes_valid` — PDF starts with `%PDF-` | Unit | TestCase | Minimum correctness check |
| S-066 | `test_cancellation_notifies_next_waitlist_entry` — signal fires, task called with correct entry_id | Integration | TenantTestCase | Core feature; broken = lost bookings |
| S-066 | `test_sim_nao_disambiguates_booking_vs_waitlist` — inbound SIM routes correctly with conflicting active appointment | Integration | TenantTestCase | Known race condition; must pass |
| S-066 | `test_waitlist_expire_task_is_idempotent` — double-run of expire_task does not double-expire | Integration | TenantTestCase | Idempotency prevents zombie entries |

---

## Architecture Concerns — CRITICAL

**E-01: S-063 — post_save Celery delay() called before transaction commits (RACE CONDITION)**
- Signal fires inside open DB transaction. Celery worker may run before commit and read stale data.
- Fix: Wrap signal handler body with `transaction.on_commit(lambda: check_prescription_safety.delay(item_id))`
- Pattern exists in `apps/core/apps.py` (`billing.services.tasks` wiring)

**E-02: S-062 — No rate limit on TOTP verify endpoint (BRUTE FORCE)**
- 1,000,000 possible 6-digit codes. 30-sec windows. No attempt counter.
- Fix: `rest_framework.throttling.UserRateThrottle` — max 3 attempts per user per 5 min. Lock account for 30 min after 5 fails.

**E-03: S-064 — CID10Code public schema routing not enforced**
- If `app_label` not set to `"core"` (SHARED_APPS), model may land in tenant schema. Silent failure.
- Fix: Set `app_label = "core"` in CID10Code Meta. Add router guard in `apps/core/routers.py`. Add integration test: `CID10Code.objects.using('public').count() > 0` inside TenantTestCase.

**E-04: S-065 — WeasyPrint requires Cairo/Pango — not in Dockerfile**
- `import weasyprint` will raise ImportError or segfault at runtime if OS libs are missing.
- Fix: Add to `/backend/Dockerfile`:
  ```dockerfile
  RUN apt-get update && apt-get install -y --no-install-recommends \
      libcairo2-dev libpango1.0-dev libffi-dev libjpeg-dev libpng-dev \
      libfreetype6-dev && rm -rf /var/lib/apt/lists/*
  ```
  Add CI test: `docker run --rm backend python -c "import weasyprint; print('ok')"`

**E-05: S-066 — WhatsApp SIM race condition: concurrent booking + waitlist notification**
- Patient responds SIM while a separate booking request creates a conflicting appointment.
- Fix: In `WaitlistEntry.accept()`, call `Appointment.objects.filter(patient=patient, status!='cancelled', start_time__gte=now, start_time__lte=now+24h).exists()` before booking. Use `select_for_update()` on WaitlistEntry during accept.

---

## Architecture Concerns — HIGH

**E-06: S-062 — JWT claim `mfa_verified` not revocable**
- Admin can't force re-auth mid-session. JWT is stateless.
- Fix: Add Redis key `mfa:revoke:{user_id}`. Middleware checks on protected requests. Expiry = MFA grace period length.

**E-07: S-063 — Cross-tenant cache: S-064 cache key missing schema_name**
- Two tenants with same diagnosis text share cached CID-10 results. LGPD risk if any patient context bleeds.
- Fix: All AI cache keys: `ai:{feature}:{schema_name}:{sha256_of_inputs}`.

**E-08: S-062 — Backup codes likely stored plaintext**
- DB breach = all backup codes compromised.
- Fix: Encrypt with `django-encrypted-model-fields.EncryptedJSONField`. Treat like passwords.

**E-09: S-066 — expire_waitlist_notification task not idempotent**
- Celery retry runs task twice. Entry expires twice. Error log spam.
- Fix: Store task_id on WaitlistEntry at dispatch time. In task, return early if status != 'notified'.

**E-10: S-063 — No DPA audit trail for AI feature flag enablement**
- Feature defaults to OFF (good) but no forensic record of when/who enabled it per tenant.
- Fix: Add `AIDPAStatus` model (public schema): `tenant, dpa_signed_date, dpa_file_url, signed_by_user`. Validate flag enablement against DPA status.

---

## Migration Plan (ordered)

| # | App | Migration | Content | Notes |
|---|-----|-----------|---------|-------|
| 1 | core | 0009_add_cid10_code.py | CID10Code model (public schema). Fields: code, description, cid_type, active, search_vector GinIndex | SHARED_APPS only; app_label="core" required |
| 2 | core | 0010_add_aiadpa_status.py | AIDPAStatus: tenant OneToOne, dpa_signed_date, dpa_file_url, signed_by_user | Optional but recommended for compliance |
| 3 | core | 0011_add_totp_device.py | TOTPDevice: user OneToOne, encrypted_secret, encrypted_backup_codes | DO NOT use django-otp migrations — build custom (avoids sequencing conflict) |
| 4 | emr | 0009_add_ai_safety_alert.py | AISafetyAlert: prescription_item FK, is_safe, severity, alert_reason, created_at | Add unique_together constraint to prevent duplicate alerts on task retry |
| 5 | emr | 0010_add_waitlist_entry.py | WaitlistEntry: appointment FK, patient FK, status, created_at, notified_at, expires_at, priority | FIFO ordering: order_by('priority', 'created_at') |
| 6 | ai | 0005_celery_beat_waitlist_tasks.py | Data migration: add PeriodicTask for expire_waitlist_notifications (every 5 min) | Public schema only (SHARED_APPS). Follows billing_migrations workaround pattern. |

**Billing conflict check:** None of these touch billing app. No conflict with `MIGRATION_MODULES = {'billing': 'billing_migrations'}`.

**django-otp:** Do NOT add `django-otp` to TENANT_APPS. Build custom `TOTPDevice` model (~50 lines with pyotp). Eliminates migration sequencing risk entirely.

---

## Dependency Risk Table

| Dependency | Install Risk | Runtime Risk | Docker Impact | Recommendation |
|------------|-------------|--------------|---------------|----------------|
| pyotp | Very Low | Very Low | None | Use it. Standard TOTP library. |
| qrcode[pil] | Low | Very Low | Medium: needs libjpeg-dev, libpng-dev in Dockerfile | Add OS deps to Dockerfile. Test in CI. |
| django-otp | Medium | Medium | None | Skip — build custom TOTPDevice with pyotp instead. Simpler + no migration conflict. |
| weasyprint | **High** | Medium | **High**: Cairo, Pango, LibFfi required in Docker | Add OS deps (see E-04 fix). Test Docker build before merge. Alternative: `reportlab` (pure Python, no OS deps, less CSS control). |

---

## Engineering Consensus Table

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════════════════
  Dimension                              Claude    Codex    Consensus
  ──────────────────────────────────────────────── ──────── ──────────────────
  1. Data model correctness?             PARTIAL   N/A      PARTIAL: gaps in uniqueness + routing
  2. API design (REST conventions)?      GOOD      N/A      GOOD: minor error code gaps only
  3. Security posture?                   AT RISK   N/A      AT RISK: brute-force + no revocation
  4. Test coverage adequate?             NO        N/A      MISSING: on_commit + race cond. tests
  5. Celery task design sound?           AT RISK   N/A      AT RISK: E-01 is critical
  6. Migration safety?                   PARTIAL   N/A      PARTIAL: import script + routing TBD
═══════════════════════════════════════════════════════════════════════════
Sprint health: 3.4/5 — READY WITH CAVEATS
Must fix before merge: E-01 (on_commit), E-02 (rate limit), E-03 (schema routing), E-04 (Dockerfile), E-05 (race condition)
```

---

## Sprint Implementation Order

```
Week 1: S-062 (MFA) + S-065 (PDF) — parallel, no dependencies
  S-062: TOTP setup/verify/login endpoints, JWT claim, backup codes (encrypted), rate limiting
  S-065: Jinja2 templates, WeasyPrint render, Dockerfile update, sign gate

Week 2: S-063 (Safety) — after S-062 base merged
  Must use on_commit() pattern (E-01)
  AISafetyAlert migration, PrescriptionSafetyChecker, WebSocket push

Week 3: S-064 (CID-10) — after core migration 0009 merged
  CID10Code model, DATASUS import command, CID10Suggester (TUSSCoder clone), schema-scoped cache

Week 4: S-066 (Waitlist) — after S-063 in review
  WaitlistEntry model, cancellation signal, WhatsApp SIM/NÃO handler + disambiguation, idempotency key
```

**Total SP: 47** (S-064 revised 5→13 SP adds 8 SP to original estimate of 39).

---

**Phase 3 complete.** Claude eng subagent: 5 critical, 5 high, 7 medium, 4 low concerns. Codex: unavailable. Sprint health: 3.4/5. 5 must-fix items before implementation starts. Passing to Phase 4.

---

# Phase 4: Final Approval Gate

## Review Summary

### Auto-decided (mechanical — no user input needed, already locked in)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | S-062 MFA: optional enforcement during pilot | Lockout = churn |
| 2 | S-064: CID10Code model + DATASUS import added to scope | Plan validation gate requires it |
| 3 | S-064: story points 5→13 | Estimate was wrong; hidden prerequisite exposed |
| 4 | S-063: LGPD gate added (default OFF, requires Anthropic DPA) | Legal exposure without it |
| 5 | S-062: Skip django-otp, build custom TOTPDevice with pyotp | Eliminates migration sequencing risk |
| 6 | S-063: transaction.on_commit() for Celery dispatch | Prevents race condition |
| 7 | All AI cache keys: `ai:{feature}:{schema_name}:{digest}` | LGPD: prevents cross-tenant data leak |
| 8 | S-062: Rate limiting on TOTP verify (3 attempts/5 min) | TOTP brute-force defense |
| 9 | S-065: Add WeasyPrint OS deps to Dockerfile | Feature won't work at all without it |
| 10 | D-01: Two-phase MFA enrollment (backup codes shown only after TOTP verified) | Backup codes before verified TOTP is a security hole |
| 11 | D-12: Safety badge must use distinct icons per state, not color alone | WCAG 1.4.1 compliance |
| 12 | D-18: AI disclaimer required inside SafetyAlertModal footer | ANVISA SaMD risk mitigation |
| 13 | D-19: Override reason required for red-severity alerts (min 10 chars) | Patient safety |

### Taste decisions — USER DECIDES

**T-1: S-065 PDF library: WeasyPrint vs reportlab**

```
WeasyPrint:
  + Full HTML/CSS rendering → prescription template is just HTML + Jinja2
  + "Receituário Azul" is just a CSS @page rule with blue border
  + Blue border spec (2px solid #1565C0) renders exactly
  - Requires Cairo/Pango in Docker (4 apt packages)
  - 2-5s first-render latency (cached after that)
  Completeness: 9/10

reportlab (pure Python):
  + Zero OS dependencies → simpler Dockerfile
  + Faster install, smaller image
  - Programmatic PDF construction (no HTML templates)
  - Controlled substance "Receituário Azul" requires manual page layout code
  - More code per story (~40% more)
  Completeness: 8/10
```

**T-2: S-066 vs basic clinic analytics — if you want to swap one story**

```
Keep S-066 (Waitlist):
  + Directly reduces no-show revenue loss
  + Reuses WhatsApp infra already built
  + Patient-facing engagement feature
  Completeness: 8/10

Replace with Basic Analytics (daily appts, weekly revenue, show rate):
  + Pilot clinic owners need visibility into their business
  + "Why is our no-show rate 40%?" — analytics answers this
  + Reduces pilot churn risk at week 3
  + Simpler to build (DB aggregations, no external API calls)
  Completeness: 8/10
```

---

## APPROVAL GATE RESULT

**User decisions:**
- T-1: **WeasyPrint** — HTML/Jinja2 templates. Dockerfile gets Cairo/Pango. Templates: `prescription.html` + `prescription_controlled.html`.
- T-2: **Keep S-066 Waitlist** — Analytics deferred to TODOS.md.

**Must-fix checklist (from Phase 3 — required before implementation):**
- [ ] E-01: `transaction.on_commit()` in S-063 signal handler
- [ ] E-02: Rate limiting on `POST /auth/mfa/verify/` (3 attempts/5 min)
- [ ] E-03: `CID10Code` model: `app_label = "core"` + router guard
- [ ] E-04: WeasyPrint OS deps in Dockerfile
- [ ] E-05: WaitlistEntry.accept() double-booking guard with select_for_update()

**Status: APPROVED — ready for implementation.**


