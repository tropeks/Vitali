# TODOS — Deferred Scope (Sprint 16 autoplan)

Generated: 2026-04-06 | Source: PLAN_SPRINT16.md autoplan phases 1-3

## Pre-GA Blockers (must complete before public launch)

- [ ] **DPA signing UI** (`/settings/dpa`): Tenant admins must sign DPA through product UI before activating `ai_scribe`. Currently bypassed via seed data. Requires: DPA acceptance form, signed document URL stored non-nullable, ANPD-compliant audit log of signing event. ~L effort.
- [ ] **`raw_transcription` encryption**: `AIScribeSession.raw_transcription` stores PHI (clinical voice transcriptions). Use `EncryptedTextField` (same pattern as `cpf` on Patient model) or encrypt at service layer before persisting. LGPD Art. 11 compliance.
- [ ] **`AIScribeSession` data retention policy**: Implement auto-delete job for non-accepted sessions after 90 days. PHI retention requirement under LGPD.

## Sprint 17 Candidates

- [ ] **`arrived_at`/`started_at` on Appointment**: Required for real `wait_time_avg` metric on dashboard. Build with digital check-in feature (doctor/receptionist marks patient as arrived). Enables wait time tracking across all clinic flows.
- [ ] **Server-side transcription (Whisper API)**: Fallback for non-Chrome/Edge browsers. Brazilian clinics use Android + Firefox; Web Speech API covers ~60-70% of devices. Whisper-based server endpoint accepts audio blob, returns transcription text to same scribe flow.
- [ ] **Fill rate metric rollout**: Once `Schedule` + `TimeSlot` is configured for pilot clinics, activate fill rate KPI on dashboard. Engineering work is small (query exists); operational work is configuring professional schedules.

## Process / Non-Code

- [ ] **Definition of Done enforcement**: Enforce frontend delivery before story closes. Sprint 16 exists as 13pts of catch-up because Sprint 15 shipped backend-only. Add frontend checklist to sprint planning template for Sprint 17 onwards.
- [ ] **`generate_mrn()` race condition**: Atomic increment using `SELECT ... FOR UPDATE` or PostgreSQL Sequence. Pre-existing issue in patient registration; low severity (unique constraint protects data integrity; retry at application layer).

## Lower Priority

- [ ] **ClaudeGateway client pooling**: Make `_client` a module-level singleton or use a cached instance to avoid creating new HTTP connection pools per scribe request. Medium priority — only matters at >10 concurrent scribe sessions.
