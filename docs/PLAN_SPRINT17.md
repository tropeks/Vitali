<!-- /autoplan restore point: /home/rcosta00/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260407-072125.md -->
<!-- autoplan: tropeks-Vitali / master / eb34bb4 / 2026-04-07 -->
# Sprint 17: Pre-GA Compliance + Scribe Hardening (v1.2.0)

**Theme:** Unblock production launch for AI features. Three pre-GA blockers in TODOS.md are LGPD compliance requirements — none can ship to real clinics without them. Plus digital check-in lays the foundation for the real-time wait-time dashboard metric that clinic owners want.

**Version target:** v1.2.0

**Stories:** S-070, S-071, S-072, S-073

**Total points:** 32 (8 + 8 + 8 + 8)

**Pre-req state (what v1.1.0 gives us):**
- Sprint 16: AI Scribe (S-069), Clinic Ops Dashboard (S-068), Sprint 15 Frontend catch-up (S-067)
- `AIDPAStatus` model (`core.0009`): `tenant`, `is_signed` (bool), `signed_at`, `signed_by`
- `AIScribeSession`: UUID PK, `encounter FK`, `raw_transcription TextField`, `soap_json JSONField`, `status`, `created_at`, `completed_at`
- `ClaudeGateway`, Celery/Redis, `EncryptedTextField` pattern (used on `Patient.cpf`)
- `FEATURE_AI_SCRIBE` flag (default OFF), DPA check in `views_scribe.py`
- Dashboard page with KPI cards and period toggle (today/week/month)
- WhatsApp gateway (Sprint 12)

---

## S-070: DPA Signing UI

**Goal:** Tenant admins can sign the AI Data Processing Agreement through the product UI. Currently `AIDPAStatus.is_signed` must be set by seed data or manual DB update — no production clinic can enable AI without this flow.

**Pre-GA blocker:** Without this, `FEATURE_AI_SCRIBE=True` is useless for real tenants. The DPA signing is a legal requirement under LGPD Art. 11 before processing sensitive health data with external AI processors (Anthropic).

**Acceptance Criteria:**
- `/settings/ai` page shows current DPA status (unsigned / signed with date and signer name).
- "Assinar DPA" button opens a modal with: full DPA text (Anthropic Data Processing Agreement), checkbox "Li e concordo com os termos do DPA", and "Confirmar Assinatura" button.
- On confirmation: `POST /api/v1/settings/dpa/sign/` sets `AIDPAStatus.is_signed=True`, records `signed_at=now()`, `signed_by=request.user`, creates AuditLog entry.
- Only users with `admin` role can sign.
- After signing: AI Scribe toggle appears in `/settings/ai` if `FEATURE_AI_SCRIBE=True` in env.
- DPA signed status shown in `/settings/ai` with signed date and signer name.
- Signing is irreversible through the UI (can only be revoked by platform admin).

**Backend:**
- `apps/core/views_dpa.py`: `DPAStatusView` (GET) + `DPASignView` (POST)
  - GET returns: `{is_signed, signed_at: dpa_signed_date.isoformat(), signed_by_name: signed_by_user.get_full_name(), ai_scribe_enabled}`
  - POST `/settings/dpa/sign/`: validates admin role, sets `AIDPAStatus.dpa_signed_date=date.today()`, `signed_by_user=request.user`, creates `AuditLog(action="dpa_sign", resource_type="ai_dpa_status")`, returns 200
  - Permission: `IsAuthenticated` + check `request.user.role.name == 'admin'`
- `apps/core/urls.py`: add paths for new views
- `apps/core/serializers.py`: `DPAStatusSerializer`

**Frontend:**
- `app/(dashboard)/settings/ai/page.tsx` — AI settings page:
  - DPA status card: signed/unsigned badge, signed_at/signer if signed
  - "Assinar DPA" button (admin only; disabled + tooltip for non-admins)
  - `DPASignModal` component: DPA text (scrollable), checkbox, confirm button, loading state
  - After signing: AI Scribe section appears with feature flag status and explanation
- `components/settings/DPASignModal.tsx`

**Tests:**
- GET `/settings/dpa/` returns `is_signed=False` before signing
- POST `/settings/dpa/sign/` sets `dpa_signed_date=today()`, `signed_by_user=user`, `is_signed` returns True
- Non-admin POST returns 403
- Double-sign is idempotent (returns 200, re-records signed_by/signed_at)
- AuditLog entry created on sign

**Story Points:** 8

---

## S-071: Scribe LGPD Hardening

**Goal:** `AIScribeSession.raw_transcription` stores PHI (clinical voice transcriptions in clear text). LGPD Art. 11 requires special-category health data to be protected with appropriate technical safeguards. Also implement 90-day automatic deletion of non-accepted sessions.

**Pre-GA blocker:** Storing unencrypted clinical transcriptions violates LGPD Art. 11 if Anthropic's data processing agreement (S-070) is not the only protection layer.

**Acceptance Criteria:**
- `AIScribeSession.raw_transcription` is stored encrypted using `EncryptedTextField` (same library as `Patient.cpf`).
- Existing records: migration encrypts existing plaintext rows (or deletes them — they are transient processing data, not patient records).
- `apps/ai/tasks.py`:`generate_soap_task` still reads `session.raw_transcription` correctly after the field change (transparent to the task layer).
- Celery Beat task `purge_old_scribe_sessions` runs daily: deletes `AIScribeSession` rows where `status != "completed"` AND `created_at < now() - 90 days`. Does NOT delete completed/accepted sessions (those contain SOAP notes doctors reviewed).
- `purge_old_scribe_sessions` runs in all tenant schemas (same pattern as `cleanup_orphaned_glosa_predictions`).
- Migration is safe: backward-compatible with existing `AIScribeSession` rows.

**Backend:**
- `apps/ai/models.py`: change `raw_transcription = models.TextField()` → `raw_transcription = EncryptedTextField()` (confirmed available: `encrypted_model_fields.fields.EncryptedTextField` at line 106 of the library)
- `apps/ai/migrations/0007_encrypt_scribe_raw_transcription.py`: data migration encrypting existing rows using `django-encrypted-fields` `migrate_to_encrypted` helper (or manual loop)
- `apps/ai/tasks.py`: add `purge_old_scribe_sessions` Celery Beat task
- `apps/ai/migrations/0008_scribe_purge_beat_schedule.py`: register `purge_old_scribe_sessions` in `PeriodicTask` (same pattern as Sprint 9 `check_tuss_staleness` beat task)
- `vitali/settings/base.py`: `SCRIBE_SESSION_RETENTION_DAYS = env.int("SCRIBE_SESSION_RETENTION_DAYS", default=90)`

**Tests:**
- `raw_transcription` value in DB is not plaintext (encrypted bytes)
- Task reads and decrypts correctly (round-trip test)
- `purge_old_scribe_sessions` deletes old processing sessions, keeps completed ones
- Purge runs across all tenant schemas

**Story Points:** 8

---

## S-072: Digital Check-in + Wait Time Dashboard

**Goal:** Receptionist marks patient as "Arrived" when they check in, doctor marks "In Room" when the appointment starts. These two timestamps enable the real `wait_time_avg` metric on the ops dashboard — which currently returns 0 forever (as noted in the code comment: "Tempo de espera real disponível após integração com check-in digital").

**Acceptance Criteria:**
- `Appointment` model adds two nullable `DateTimeField` columns: `arrived_at` and `started_at`.
- Waiting room page: "Chegou" button on each waiting appointment (receptionist) → sets `arrived_at`, changes status to `"waiting"`.
- "Iniciar Atendimento" button on in-progress appointment (doctor/receptionist) → sets `started_at`, changes status to `"in_progress"`.
- `GET /api/v1/analytics/overview/?period=...` now returns `wait_time_avg_min`: avg of `(started_at - arrived_at)` for completed appointments with both timestamps set, in the period. Returns `null` if no data.
- Dashboard KPI card "Tempo Médio de Espera" shows value (in minutes) or "—" if null.
- `POST /api/v1/appointments/{id}/check-in/` — sets `arrived_at=now()`, status→`waiting`
- `POST /api/v1/appointments/{id}/start/` — sets `started_at=now()`, status→`in_progress`
- Waiting room auto-refresh shows arrived patients highlighted.

**Backend:**
- `apps/emr/migrations/0013_appointment_arrived_started.py`: add `arrived_at`, `started_at` to `Appointment`
- `apps/emr/views.py` (`AppointmentViewSet`): add `@action(detail=True, methods=['post']) check_in` and `start` actions
- `apps/analytics/views.py` (`OverviewView`): compute `wait_time_avg` from `Appointment.objects.filter(arrived_at__isnull=False, started_at__isnull=False, ...)`

**Frontend:**
- `app/(dashboard)/waiting-room/page.tsx`: add "Chegou" button per appointment row; auto-refresh every 30s
- `app/(dashboard)/dashboard/page.tsx`: add 5th KPI card "Tempo de Espera" with `wait_time_avg_min` value
- `components/dashboard/WaitTimeCard.tsx` — shows "X min" or "—" (no data)

**Tests:**
- `check-in` action sets `arrived_at`, status `waiting`
- `start` action sets `started_at`, status `in_progress`
- `wait_time_avg` computed correctly (minutes, rounded to 1 decimal)
- `wait_time_avg` is `null` when no appointments have both timestamps
- Double check-in is idempotent (does not overwrite existing `arrived_at`)

**Story Points:** 8

---

## S-073: Whisper API Transcription Fallback

**Goal:** Web Speech API only works in Chrome and Edge (covers ~65% of Brazilian clinic devices — many use Android Chrome, but Firefox and Safari are excluded). Add a server-side audio upload endpoint using OpenAI Whisper API as fallback, so the Scribe feature works on all browsers.

**Acceptance Criteria:**
- `ScribeButton.tsx` detects if `window.SpeechRecognition || window.webkitSpeechRecognition` is available.
- If available: existing Web Speech API text flow (current behavior).
- If NOT available: shows "Gravar Áudio" button (microphone icon). Click starts `MediaRecorder` (webm/opus). Stop button ends recording. Audio blob POSTed to `POST /api/v1/encounters/{id}/scribe/transcribe/`.
- `POST /scribe/transcribe/` accepts `audio` (multipart, webm/mp4, max 25MB) → calls Whisper API → returns `{transcription: "..."}` → client continues with existing scribe flow (same as text input).
- Progress: recording timer shows elapsed seconds. Max recording: 5 minutes.
- Error handling: file too large → 400, Whisper API error → 503 with retry prompt.
- Feature flag: `FEATURE_WHISPER_FALLBACK` (default **ON** — users without Web Speech API get fallback automatically; kill switch available).
- Sprint guard: if `AudioRecorder.tsx` is not merged by day 5, defer frontend Whisper piece to Sprint 18 (backend endpoint still ships).

**Backend:**
- `apps/emr/views_scribe.py`: `ScribeTranscribeView`
  - POST `/encounters/{id}/scribe/transcribe/`
  - Accepts `audio` file (multipart), validates size < 25MB and content-type
  - Calls `openai.Audio.transcriptions.create(model="whisper-1", file=..., language="pt")` via `OpenAIGateway`
  - Returns `{transcription: "..."}` — client feeds this into existing scribe start flow
  - Requires `FEATURE_WHISPER_FALLBACK=True` and same DPA check as `ScribeStartView`
- `apps/emr/services/whisper.py`: `WhisperGateway.transcribe(audio_bytes, content_type) -> str`
- `vitali/settings/base.py`: `OPENAI_API_KEY = env("OPENAI_API_KEY", default="")`, `FEATURE_WHISPER_FALLBACK = env.bool("FEATURE_WHISPER_FALLBACK", default=True)` (ON by default)
- `vitali/settings/production.py`: raise `DATA_UPLOAD_MAX_MEMORY_SIZE = 26_214_400` (25 MB) to allow audio upload
- `requirements/base.txt`: add `openai>=1.0` (not currently installed — needed for Whisper API client)
- Infra: ensure nginx `client_max_body_size` is at least 26 MB (default is 1 MB)
- `apps/emr/urls.py`: add `path('encounters/<uuid:encounter_id>/scribe/transcribe/', ScribeTranscribeView.as_view(), ...)`

**Frontend:**
- `components/emr/ScribeButton.tsx`: detect Speech API availability on mount
- `components/emr/AudioRecorder.tsx`: `MediaRecorder` wrapper, recording timer, stop button, audio preview
- Shows fallback UI (record button) when Speech API unavailable; integrates seamlessly with existing scribe flow

**Tests:**
- Feature flag OFF → 404
- Valid webm upload → Whisper called, transcription returned
- File > 25MB → 400
- Invalid content type → 400

**Story Points:** 8

---

## Technical Scope

### New models / model changes
- `Appointment`: add `arrived_at DateTimeField null=True`, `started_at DateTimeField null=True`
- `AIScribeSession.raw_transcription`: change to `EncryptedTextField`

### New migrations
- `apps/ai/migrations/0007_encrypt_scribe_raw_transcription.py` — data migration
- `apps/ai/migrations/0008_scribe_purge_beat_schedule.py` — Celery Beat task registration
- `apps/emr/migrations/0013_appointment_arrived_started.py`

### New files
- `backend/apps/core/views_dpa.py`
- `backend/apps/core/serializers.py` (DPA serializer addition)
- `backend/apps/emr/services/whisper.py`
- `frontend/app/(dashboard)/settings/ai/page.tsx`
- `frontend/components/settings/DPASignModal.tsx`
- `frontend/components/dashboard/WaitTimeCard.tsx`
- `frontend/components/emr/AudioRecorder.tsx`

### Modified files
- `backend/apps/ai/models.py` — encrypt raw_transcription
- `backend/apps/ai/tasks.py` — add purge task
- `backend/apps/analytics/views.py` — add wait_time_avg to OverviewView
- `backend/apps/emr/views.py` — check_in / start actions
- `backend/apps/emr/views_scribe.py` — ScribeTranscribeView
- `backend/apps/emr/urls.py` — new paths
- `backend/apps/core/urls.py` — DPA paths
- `backend/vitali/settings/base.py` — new settings
- `frontend/app/(dashboard)/dashboard/page.tsx` — 5th KPI card
- `frontend/app/(dashboard)/waiting-room/page.tsx` — check-in button
- `frontend/components/emr/ScribeButton.tsx` — Speech API detection + fallback

---

## Non-Goals (deferred)
- ICP-Brasil digital signature on DPA (S-070 uses checkbox + audit log; cryptographic signature is Phase 3)
- Whisper for languages other than Portuguese (language fixed to `pt`)
- Real-time audio streaming to Whisper (batch upload only)
- Patient portal access to scribe sessions
- Scribe session editing history (only final SOAP edit is tracked)
- Patient consent UX for voice transcription data (LGPD Art. 7/11 — deferred to Sprint 18, tracked separately)

---

## Pre-Implementation Blockers (must fix before coding)

| # | Story | Blocker |
|---|-------|---------|
| B1 | S-071 | Data migration `RunPython` must import the **real** model (`from apps.ai.models import AIScribeSession`), not the frozen historical model — otherwise encryption is silently skipped |
| B2 | S-071 | Confirm `ai` app is in `TENANT_APPS` (not `SHARED_APPS`) so the migration runs per tenant schema |
| B3 | S-070 | Re-sign guard: POST must NOT overwrite original `dpa_signed_date` — only sign if `not dpa_status.is_signed`; re-sign returns 200 without mutating or logging |
| B4 | S-070 | GET must handle `AIDPAStatus.DoesNotExist` gracefully (return synthetic unsigned response, not 404) |
| B5 | S-073 | `DATA_UPLOAD_MAX_MEMORY_SIZE` in `production.py` is 10 MB — 25 MB audio will hit `RequestDataTooBig`. Raise to 26 214 400. Also check nginx `client_max_body_size` (default 1 MB). |
| B6 | S-071 | Add an explicit test that calls the `RunPython` migration function directly on a plaintext row and asserts round-trip decryption — standard migrate/test flow won't catch the frozen-model bug |

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/autoplan` | Scope & strategy | 1 | DONE_WITH_CONCERNS | S-073 underestimated (~13pts); patient consent gap (LGPD Art.7/11); S-073 OFF-default wrong; S-071 migration is highest risk |
| Eng Review | `/autoplan` | Architecture & tests | 1 | DONE_WITH_CONCERNS | 6 concrete blockers (see above); weakest test: S-071 migration function; migration numbering confirmed correct |
| Design Review | — | UI/UX gaps | 0 | PENDING | — |

**VERDICT:** APPROVED — blockers B1–B6 incorporated into plan. Taste decisions locked: S-073 stays in sprint with day-5 cut gate; `FEATURE_WHISPER_FALLBACK` defaults ON.
