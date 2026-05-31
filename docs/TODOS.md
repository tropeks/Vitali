# TODOS — Deferred Scope (Sprint 16 autoplan)

Generated: 2026-04-06 | Source: PLAN_SPRINT16.md autoplan phases 1-3
Last reconciled with shipped state: 2026-05-20

## Pre-GA Blockers (must complete before public launch)

- [x] **DPA signing UI** (`/configuracoes/ai`): shipped as part of the Sprint
  15-17 catch-up — `AIDPAStatus` model + migration `core/0009_aidpastatus.py`,
  `views_dpa.py`, `DPASignModal` and the operational `/configuracoes/ai` page
  (now on the v2.0 design system) drive the signed/non-signed state through
  the canonical `getDpaStatusMeta` adapter.
- [x] **`raw_transcription` encryption**: `AIScribeSession.raw_transcription`
  is an `EncryptedTextField` (`apps/ai/models.py:188`) backed by migration
  `apps/ai/migrations/0007_encrypt_scribe_raw_transcription.py`.
- [x] **`AIScribeSession` data retention policy**: `purge_old_scribe_sessions`
  Celery task (`apps/ai/tasks.py:100`) deletes non-accepted sessions older
  than `SCRIBE_SESSION_RETENTION_DAYS` (default 90). Beat schedule registered
  via data migration `apps/ai/migrations/0008_scribe_purge_beat_schedule.py`.

## Sprint 17 Candidates

- [x] **`arrived_at`/`started_at` on Appointment**: shipped in Sprint 25 —
  `apps/emr/models.py:254-255`. Powers the operational `wait_time_avg` and
  the dedicated check-in / start cascades.
- [x] **Server-side transcription (Whisper API)**: `WhisperGateway`
  (`apps/emr/services/whisper.py`) wired into `views_scribe.py` behind the
  `FEATURE_WHISPER_FALLBACK` flag.
- [ ] **Fill rate metric rollout**: query path is live; flipping the dashboard
  KPI on depends on operational `Schedule` + `TimeSlot` configuration in the
  pilot tenants, not on engineering work.

## Process / Non-Code

- [ ] **Definition of Done enforcement**: process change for sprint planning;
  no code action.
- [x] **`generate_mrn()` race condition**: fixed in commit `07cb3fa`
  (`fix: serialize patient MRN generation`).

## Lower Priority

- [ ] **i18n: internationalize the codebase** (currently pt-BR only despite 4
  advertised languages) — Phase 3, **not blocking pilot**. The i18n
  *scaffolding* is wired (settings, `LANGUAGES`, `LocaleMiddleware`,
  `PreferredLanguageMiddleware`, `preferred_language`, `/users/me/language/`),
  but `backend/locale/` has zero `.po`/`.mo` catalogs and source strings are
  not `gettext`-marked (one lone import in `apps/core/admin.py`), and the
  Next.js frontend has no i18n library — so the platform effectively serves
  pt-BR only. Full phased plan in `docs/I18N.md`.
- [x] **ClaudeGateway client pooling** (2026-05-20): the underlying
  `anthropic.Anthropic` client is cached at module level by
  `(api_key, timeout)` so repeated `ClaudeGateway()` instantiations on the
  hot path reuse the same HTTP connection pool. `reset_anthropic_client_cache()`
  is exported for tests. Regression coverage:
  `apps/ai/tests/test_gateway.py::test_reuses_anthropic_client_across_gateways_with_same_credentials`
  and `::test_different_credentials_get_distinct_clients`.
