# Sprint 9 — AI Production Readiness + Glosa Prediction

<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260331-152419.md -->

**Status:** APPROVED — /autoplan review complete 2026-03-31
**Date:** 2026-03-31
**Branch:** feature/sprint9-ai-expansion
**Epics:** E-010 (TUSSSyncLog), E-011 (TenantAIConfig), E-012 (Glosa Prediction)

---

## Context

Sprint 8 shipped AI TUSS Auto-Coding on master. Three things block full production use:

1. **No TUSSSyncLog** — ops cannot verify the TUSS table is current before enabling AI.

2. **Global-only feature flag** — `FEATURE_AI_TUSS` cannot be toggled per-tenant. When a
   second clinic onboards, there is no per-clinic control.

3. **LLMGateway unused beyond TUSS** — the abstraction was retained in Sprint 8 for
   "Sprint 9/10 AI features." The highest-value next use is Glosa Prediction: given a
   procedure code + insurer + CID-10, predict denial risk. This is revenue-protective
   (clinic owners care about denial recovery) and builds on the billing-specific data moat
   from Sprint 8. SOAP summarization was considered and rejected (CEO review: unvalidated
   demand, regulatory risk, no defensibility vs generic NLP competitors).

Sprint 9 ships all three.

---

## CEO Review — Key Decisions

**Decision A: SOAP summarization → Glosa Prediction (strategic pivot)**
User chose Glosa Prediction. Reason: revenue impact vs documentation nicety, billing moat,
no CFM regulatory risk. SOAP summarization deferred to Sprint 11+ pending clinician interviews.

**Decision B: Per-tenant toggle → Django Admin only (auto-decided, P5)**
Full API + frontend UI is over-engineered for current one-clinic state. Django Admin model
(zero new endpoints, zero new frontend) ships the same capability in 2 hours.
Escalate to full API when second clinic is actively onboarding.

**Decision C: TUSSSyncLog — backend + minimal frontend (auto-decided, P2)**
Status badge on billing overview is in-scope. No separate page.

---

## Stories

### S-032 — TUSSSyncLog (P2, production gate)

**Problem:** `import_tuss` runs silently. Ops enabling `FEATURE_AI_TUSS` cannot confirm
the TUSS table is current without a direct DB query.

**Backend:**
- `TUSSSyncLog` model in `apps/core/models.py` (SHARED_APPS — lives in PUBLIC schema):
  IMPORTANT: TUSSSyncLog MUST be in SHARED_APPS alongside TUSSCode. The `import_tuss`
  command runs in public schema context (no tenant set); writing to a TENANT_APP model
  would crash. Since the TUSS table is global (one shared table), the sync log is global too.
  ```
  id (UUID PK, auto)
  ran_at (auto_now_add, db_index)
  source (CharField: 'management_command' | 'api' | 'scheduled')
  row_count_total (PositiveIntegerField)
  row_count_added (PositiveIntegerField)
  row_count_updated (PositiveIntegerField)
  status (CharField: 'success' | 'partial' | 'error')
  error_message (TextField, blank,
    help_text="Scrubbed: connection strings stripped, max 200 chars")
  duration_ms (PositiveIntegerField, default=0)
  ```
- Update `import_tuss` management command to:
  - Record start time, count rows, write `TUSSSyncLog` entry at exit (success or error).
  - Existing command already surfaces `added`/`updated` counts — just persist them.
  - Command is at `apps/core/management/commands/import_tuss.py` (NOT apps/billing/).
- Endpoint: `GET /api/v1/ai/tuss-sync-status/` (admin permission).
  Returns: `{"last_syncs": [...5 entries], "table_row_count": N, "last_sync_age_days": N}`.
- Migration: `apps/core/migrations/000N_tussynclog_tenantaiconfig.py` (one migration in
  apps.core for both S-032 TUSSSyncLog and S-033 TenantAIConfig — both are in public schema).

**Frontend:**
- On `/billing` overview page: TUSS DB sync status badge.
  - Placement: secondary row below page `<h1>`, right-aligned. `min-h-[24px]` reserved regardless of admin
    status — prevents layout shift when conditionally hidden for non-admins.
  - Visible only to admin role users (`user.role === 'admin'`).
  - States:
    - Green `bg-green-100 text-green-700`: last sync < 30 days
    - Yellow `bg-yellow-100 text-yellow-700`: last sync 30-90 days OR `status === 'partial'`
    - Red `bg-red-100 text-red-700`: last sync > 90 days, never synced, or `status === 'error'`
    - NOTE: `partial` status from backend always maps to yellow regardless of sync age — partial sync
      means incomplete data. Tooltip: "Última sincronização incompleta — verifique o log."
  - `aria-label="TUSS DB sincronizado há N dias — status: OK|atenção|crítico"` (derived from state)
  - Fetch `GET /api/v1/ai/tuss-sync-status/` on page load. Silently hides if non-admin.

**Tests:** `test_tuss_sync_log.py` — model creates correctly, management command writes log,
endpoint requires admin, returns correct structure (sync age calculation).
- ADD: TUSSSyncStatusView zero-rows case returns "never synced" state (last_sync_age_days=None)
- ADD: Non-admin user cannot access /tuss-sync-status/ (403, not just admin tested)

---

### S-033 — TenantAIConfig (P2, multi-clinic gate)

**Problem:** `FEATURE_AI_TUSS` is a global env-var. No per-clinic control.

**Scope (Django Admin only — no new API endpoints, no new frontend pages):**

- `TenantAIConfig` model in `apps/core/models.py` (SHARED_APPS — lives in PUBLIC schema):
  ```
  id (UUID PK, auto)
  tenant (OneToOneField to tenants.Tenant, on_delete=CASCADE, related_name='ai_config')
  ai_tuss_enabled (BooleanField, default=False)
  ai_glosa_prediction_enabled (BooleanField, default=False)
  rate_limit_per_hour (PositiveIntegerField, default=500,
    help_text="Default 500/hr covers 10-item guide creation with edits. Reduce per-tenant if cost control needed.",
    validators=[MinValueValidator(10), MaxValueValidator(2000)])
  monthly_token_ceiling (PositiveIntegerField, default=500000,
    help_text="Claude tokens/month ceiling. AI silently degrades when exceeded.")
  created_at (auto_now_add)
  updated_at (auto_now)
  ```
  IMPORTANT: `TenantAIConfig` MUST be in `SHARED_APPS` (public schema), NOT in tenant schema.
  Reasoning: Django Admin runs in public schema context; tenant-schema models registered in Admin
  will either crash (table not found) or silently corrupt data. Using a real FK to `Tenant`
  also provides cross-tenant uniqueness via DB-level constraint. This is the standard
  django-tenants pattern for per-tenant configuration.

- `get_tenant_ai_config(schema_name: str) -> TenantAIConfig` helper in `apps/ai/services.py`:
  - `cache.get_or_set(f"ai:config:{schema_name}", ..., timeout=300)`.
  - Looks up via `TenantAIConfig.objects.using('default').get(tenant__schema_name=schema_name)`.
  - Returns a default `TenantAIConfig()` instance (unsaved) if no row exists. Never raises.

- Monthly token ceiling check: use Redis counter, NOT a full-table aggregate.
  - Key: `ai:tokens:{schema}:{YYYY-MM}`. TTL: midnight end-of-month.
  - On every `AIUsageLog` creation, run `cache.incr(monthly_key, tokens_in + tokens_out)`.
  - `check_monthly_ceiling(schema)` reads the counter. On Redis miss, seeds from DB query
    with `created_at__range=(month_start, month_end)` (sargable on existing `created_at` index).
  - This avoids per-call DB aggregate and eliminates race condition.

- Update `rate_limiter.is_rate_limited(tenant_schema, limit=None)`:
  - Add optional `limit` parameter. If None, falls back to `settings.AI_RATE_LIMIT_PER_HOUR`.
  - `TUSSCoder.suggest()` and `GlosaPredictor.predict()` pass `get_tenant_ai_config(schema).rate_limit_per_hour`.
  - Per-tenant rate limit is now enforced (was a dead field before this fix).

- Update circuit breaker keys to include feature name:
  - `ai:cb:failures:{tenant}:{feature}` and `ai:cb:open:{tenant}:{feature}`
  - `feature` = `'tuss'` or `'glosa'`. Two independent circuits per tenant.
  - `is_open(tenant_schema, feature)`, `record_failure(tenant_schema, feature)`,
    `record_success(tenant_schema, feature)`.
  - TUSS failures don't trip Glosa circuit and vice versa.

- Update `TUSSCoder.suggest()`:
  - Replace `settings.FEATURE_AI_TUSS` check with `get_tenant_ai_config(schema).ai_tuss_enabled`.
  - Keep `settings.FEATURE_AI_TUSS` as hard-off global kill-switch (env override).
  - Also check `settings.FEATURE_AI_GLOSA` (new global env-var kill-switch) in `GlosaPredictor.predict()`.
    Pattern: `if not getattr(settings, 'FEATURE_AI_GLOSA', True): return PredictionResult(degraded=True)`.
    Add to `.env.example`: `FEATURE_AI_GLOSA=true`.
  - Check monthly token ceiling via Redis counter.
  - Pass `rate_limit_per_hour` to `is_rate_limited`.
  - Pass `feature='tuss'` to circuit breaker calls.

- Update `TUSSSuggestView` to use `get_tenant_ai_config`.
  Update `TUSSSuggestFeedbackView`: when feature disabled, return `{"detail": "...", "accepted": false}`
  with HTTP 200 (not 404) — do not drop feedback silently, but do not error.

- `post_save` signal on `Tenant` (in `apps/core/signals.py`): auto-create `TenantAIConfig` row
  with defaults (all disabled) when a new tenant is provisioned. This makes every tenant's AI
  config visible in Django Admin from day one — "all disabled" is an explicit visible state,
  not a silent absence. Prevents ops from misreading "no config row" as low adoption.
  IMPORTANT: Register this signal in `apps/core/apps.py` `CoreConfig.ready()`:
  `from apps.core import signals  # noqa` — without this, the signal never fires.

- **Backfill for existing tenants:** Add a data migration (or one-time `python manage.py shell`
  command) to create `TenantAIConfig` rows for all existing `Tenant` records that don't have one:
  ```python
  for tenant in Tenant.objects.all():
      TenantAIConfig.objects.get_or_create(tenant=tenant)
  ```
  Include in the apps.core migration as a `RunPython` step (safe for public-schema shared model).

- Django Admin: Register `TenantAIConfig` in `apps/core/admin.py` (alongside other shared models).
  No new API endpoint, no new frontend page.

- Migration: `apps/core/migrations/000N_tussynclog_tenantaiconfig.py` — one migration
  for both TUSSSyncLog (S-032) and TenantAIConfig (S-033) since both are in apps.core.
  apps/ai migration for S-034: `apps/ai/migrations/0003_sprint9_glosaprediction.py`.

**Tests:** `test_tenant_ai_config.py` — config created, defaults to disabled,
`get_tenant_ai_config` cache hit/miss, TUSSCoder respects per-tenant toggle,
monthly ceiling blocks calls when exceeded.
- ADD: post_save signal creates TenantAIConfig row when new Tenant is provisioned
- ADD: monthly_token_ceiling DB-seed on Redis miss: flush cache → call check_monthly_ceiling → verify seeds from AIUsageLog aggregate
- ADD: monthly_token_ceiling blocks GlosaPredictor (not just TUSSCoder)
- ADD: `get_tenant_ai_config` returns default (unsaved) when no row — verify no pk, all fields are disabled defaults
- NOTE: Cache TTL is 5 minutes. Django Admin saves do NOT invalidate the cache. Ops enabling/disabling AI will see a max 5-minute lag. Document this in TenantAIConfig's help_text or Django Admin note.

---

### S-034 — Glosa Prediction (new AI feature)

**Problem:** A faturista creating a billing guide has no signal about whether the procedure
codes, insurer, and CID-10 combination is likely to be denied. The clinic discovers denials
only after batch submission — often weeks later. Denial = deferred revenue + appeal overhead.

**How it works:**
- Input: `tuss_code` + `insurer_ans_code` + `cid10_codes` (list) + `guide_type`
- LLM: Predicts denial risk (low / medium / high) + short reason in PT-BR
- Data moat: as guides accumulate + glosa retorno XML is processed, the system builds a
  proprietary insurer-specific denial pattern that no generic EMR competitor can replicate.
- v1 is LLM zero-shot reasoning from ANS rules (age/sex incompatibility, carência, known
  uncovered procedures). Future versions can add RAG over accumulated Glosa records.

**Backend:**

- `GlosaPrediction` model in `apps/ai/models.py`:
  ```
  id (UUID PK, auto)
  guide (ForeignKey to billing.TISSGuide, on_delete=PROTECT, null=True, blank=True)
  tuss_code (CharField max_length=20)
  insurer_ans_code (CharField max_length=20)
  cid10_codes (JSONField, default=list)
  guide_type (CharField max_length=20)
  risk_level (CharField choices: 'low'|'medium'|'high', db_index=True)
  risk_reason (TextField)
  risk_code (CharField max_length=5, blank=True,
    help_text="GLOSA_REASON_CODE best match, if applicable")
  usage_log (FK to AIUsageLog, null=True, on_delete=SET_NULL)
  was_denied (BooleanField null=True, blank=True,
    help_text="Backfilled by retorno parser when denial confirmed")
  created_at (auto_now_add)
  ```

- `GlosaPredictor` class in `apps/ai/services.py`:
  - `predict(tuss_code, insurer_ans_code, cid10_codes, guide_type, schema_name) -> PredictionResult`
  - `PredictionResult(risk_level, risk_reason, risk_code, degraded, cached)`
  - Uses `LLMGateway` (same Claude Haiku, same circuit breaker, same rate limiter).
  - Checks `get_tenant_ai_config(schema).ai_glosa_prediction_enabled`.
  - Cache key: `ai:glosa:{schema}:{full_sha256_hex_of(tuss|insurer|sorted_cid10|guide_type)}`.
    Use full SHA256 hexdigest (not truncated). TTL: 24 hours (NOT 7 days — insurer coverage
    rules can change; stale false-negatives are worse than a cache miss).
  - Prompt (system): "Você é um especialista em faturamento TISS brasileiro. Analise se a
    combinação de procedimento, operadora e diagnóstico abaixo tem risco de glosa (negativa)
    pela operadora. Responda em JSON: {risk_level, risk_reason, risk_code}."
  - Prompt (user): Injects procedure, insurer name, CID-10 list, guide type.
  - Prompt injection guard:
    - `tuss_code`: from TUSSCode DB row (validated by pk) — safe
    - `insurer_name`: user-editable CharField; strip newlines, limit to 100 chars before inject
    - `insurer_ans_code`: validate `^[0-9]{1,20}$` before inject
    - `cid10_codes`: strip all non-alphanumeric chars per code before inject
    - All injected fields: replace `{` and `}` (prompt template injection guard, same as TUSSCoder)
  - Creates `AIUsageLog` entry. Creates `GlosaPrediction` record.
  - Returns `PredictionResult(risk_level='low', degraded=True)` on any error (fail-open).

- New `AIPromptTemplate` record for `glosa_predict` seeded via management command
  `python manage.py seed_prompt_templates` (NOT in migration — migrations with `RunPython` data ops
  against tenant schemas are fragile in multi-tenant setups; use a post_migrate signal or
  management command instead).

- Endpoint: `POST /api/v1/ai/glosa-predict/`
  - Permission: `billing.read` (faturistas + admins)
  - Body: `{"tuss_code_id": N, "insurer_id": N, "cid10_codes": ["X00"], "guide_type": "sadt"}`
  - Response: `{"risk_level": "medium", "risk_reason": "...", "risk_code": "01", "cached": bool, "degraded": bool}`
  - Feature gate: checks `get_tenant_ai_config(schema).ai_glosa_prediction_enabled`.
    Returns `{"degraded": true, "risk_level": "low"}` when disabled (not 404 — guide form stays functional).

- `retorno_parser.py` update: when a guide is marked as denied/partially denied, set
  `GlosaPrediction.was_denied=True` for all `GlosaPrediction` records matching `guide_id`.
  Match is GUIDE-LEVEL only (not item-level) — TISS retorno XML glosa elements do not include
  procedure codes per ANS TISS 4.01.00 spec. Per-item granularity deferred to Sprint 11 when
  item-level denial codes may be available via extended retorno elements.
  NOTE: This requires `GlosaPrediction.guide` to be non-null at backfill time (see Linking section).

- **Prediction-to-Guide linking (solves null guide_id problem):**
  When the guide creation form submits (`POST /api/v1/billing/guides/`), include
  `glosa_prediction_ids: [uuid, ...]` in the request payload — the IDs of all `GlosaPrediction`
  records created during the current form session.
  The guide create serializer accepts `glosa_prediction_ids` as a write-only list field.
  The guide create view: after saving the guide, runs:
  ```python
  if ids:  # guard: skip DB round-trip when no predictions were made
      GlosaPrediction.objects.filter(
          id__in=ids, guide__isnull=True
      ).update(guide=guide)
  ```
  NOTE: Normal tenant ORM — no `.using('default')` needed. django-tenants sets the
  correct search_path on every tenant request.
  The frontend: tracks prediction IDs in form state (stored alongside each item row's badge result).

- **Dismissed signal: deferred to Sprint 10.** The `has_dismissed_high_risk` signal has no
  viable implementation path in Sprint 9 because: (a) `GlosaPrediction.guide` is null at form time,
  (b) guide creation may fail after predict, (c) the through-table design requires additional
  migration work. Removing from Sprint 9 scope. The `was_denied` backfill (when guide is linked)
  is the feedback signal for v1. Override patterns are Sprint 10.

- URL in `apps/ai/urls.py`.
- Serializer in `apps/ai/serializers.py`.

- **Orphaned prediction cleanup:** Add a Celery beat task `cleanup_orphaned_glosa_predictions`
  (in `apps/ai/tasks.py`, scheduled nightly) that deletes `GlosaPrediction` rows where
  `guide__isnull=True AND created_at__lt=now()-7days`. Log count deleted. Idempotent.
  This handles abandoned guide form sessions.

- **Missing prompt template handling:** `GlosaPredictor.predict()` must handle the case where
  no `AIPromptTemplate` named 'glosa_predict' exists (template not yet seeded). Fail-open:
  return `PredictionResult(risk_level='low', degraded=True)` and log an `AIUsageLog` with
  `event_type='degraded'`. Do NOT raise. Ops will see the degraded events in the AI usage dashboard.

- **Monthly ceiling Redis/DB atomicity note:** `cache.incr(monthly_key, tokens_in+tokens_out)`
  runs after the `AIUsageLog.save()` completes (in a `post_save` signal or explicit call in
  the service). If Redis is unavailable at that moment, the counter drifts low (not high).
  Fail direction is permissive (more calls allowed), not restrictive. Acceptable for pilot.

**Frontend:**

- On guide creation form (`billing/guides/new/page.tsx`), in the TISS items table:
  - Each item row gets a glosa risk badge (when `ai_glosa_prediction_enabled`).
  - After TUSS code is selected (via TUSSCodeSearch combobox), fetch
    `POST /api/v1/ai/glosa-predict/` with the row's tuss_code_id + current guide's insurer + CID-10.
  - Badge states:
    - `loading`: small spinner (300ms debounce — don't fire until TUSS code stabilizes)
    - `low`: grey pill "Baixo risco"
    - `medium`: yellow pill "Risco médio" + tooltip with `risk_reason`
    - `high`: red pill "Alto risco" + tooltip with `risk_reason`
    - `degraded/disabled`: no badge (invisible — guide form works normally)
  - Design tokens from DESIGN.md: yellow = `text-yellow-700 bg-yellow-50`, red = `text-red-700 bg-red-50`.
  - AbortController per item row (cancel stale requests when tussCodeId changes).
  - Debounce ALSO triggers when `insurerId` changes — re-debounce all item rows simultaneously.
    This prevents 10 concurrent POST requests when a 10-item guide's insurer field changes.
    Document in TenantAIConfig: for clinics using Glosa Prediction heavily, recommend
    `rate_limit_per_hour >= 500` in Django Admin.

**New component:** `frontend/components/billing/GlosaRiskBadge.tsx`

Props: `{ tussCodeId: number, insurerId: number | null, cid10Codes: string[], guideType: string }`

Internal states: `idle | loading | loaded | error | degraded`
- `idle`: renders nothing (before tussCodeId set)
- `loading`: skeleton shimmer `animate-pulse w-16 h-5 rounded-full bg-gray-100` (NOT a spinner — avoids visual collision with TUSSSuggestionInline's spinner in the same row)
- `loaded`: pill badge
- `error`: muted `bg-gray-100 text-slate-400` pill "Risco indisponível" with `title="Serviço de predição indisponível"`
- `degraded`: no badge rendered (feature disabled — invisible to user)

Guard: if `insurerId` is null, do NOT fetch. Render nothing. Wait until insurer is selected.

Guard: if `cid10Codes.length === 0`, do NOT fetch. Render a grey informational pill:
"Diagnóstico não informado" (`bg-gray-100 text-gray-400 text-xs`) with title="Adicione CID-10 para calcular risco de glosa".

Fetches when `tussCodeId` OR `cid10Codes` changes (debounced 300ms). AbortController per row.
NOTE: cid10Codes must be in the dependency array. Editing diagnoses after TUSS is selected
must re-trigger — otherwise badge shows stale risk from the previous CID-10 list.

Badge anatomy (all levels):
- Container: `<div role="status" aria-live="polite">` — screen reader announces state transitions
- Pill: `inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border`
- Icon: lucide-react `AlertTriangle` (16px) for high/medium, `CheckCircle2` for low, no icon for error/degraded
- Colors (matching existing DESIGN.md badge recipe — note `100` not `50`):
  - high: `bg-red-100 text-red-700 border-red-200`
  - medium: `bg-yellow-100 text-yellow-700 border-yellow-200`
  - low: `bg-gray-100 text-gray-600 border-gray-200`
  - error: `bg-gray-100 text-slate-400 border-gray-100`
- Text: sentence case ("Alto risco", not "ALTO RISCO")

Tooltip (medium + high + low):
- Use existing shadcn `Tooltip` / Radix `TooltipPrimitive` (project pattern)
- Trigger: both hover AND keyboard focus (`tabIndex={0}` on the pill, or wrap in `<button type="button">`)
- Max width: `max-w-xs` (320px)
- Content: `risk_reason` + action hint for high/medium: "Verifique o código TUSS e os diagnósticos antes de submeter. Você pode continuar mesmo assim."
- Low risk tooltip: "Baixo risco de glosa para esta combinação de procedimento, operadora e diagnóstico."
- `role="tooltip"` + `aria-describedby` on the trigger

Column placement in guide items table:
- Badge column is placed IMMEDIATELY AFTER the TUSS code column (before description)
- Visual sequence per row: [#] [TUSS code + combobox] [risk badge — `w-28` fixed] [description] [qty] [unit value] [total] [remove]
- Fixed `w-28` on badge column prevents layout jank as state changes
- On narrow viewports: badge column collapses to icon-only (no text)

**NOTE — Dismissal signal deferred to Sprint 10:** `has_dismissed_high_risk` has no viable
implementation path in Sprint 9 (null guide_id at prediction time, complex through-table).
See Decision 27. DO NOT implement any dismiss endpoint, payload field, or signal in Sprint 9.

**Tests:**
- `test_glosa_predictor.py`: predict returns result, respects feature flag, respects circuit
  breaker, respects rate limiter, creates AIUsageLog + GlosaPrediction, fail-open on error,
  prompt injection guard on cid10 input, cache hit returns cached=True.
  - ADD: cache TTL test — verify cache key set with 24h timeout (not 7 days)
  - ADD: monthly ceiling blocks predict (patch check_monthly_ceiling to return True)
- `test_views_glosa.py`: endpoint requires auth + billing.read, gate returns degraded when
  feature disabled (not 404), invalid tuss_code_id returns 400.
  - ADD: glosa_prediction_ids with already-linked IDs (guide__isnull=True filter is idempotent)
- `test_retorno_parser_feedback.py`: backfill sets `was_denied=True` on matching prediction.
  - ADD: guide with multiple GlosaPredictions — all are updated, not just first
- `test_management_commands.py` (new or extend test_services.py):
  - ADD: seed_prompt_templates idempotent — run twice, verify same AIPromptTemplate count, no duplicate rows

**E2E (Playwright) — new file `frontend/e2e/billing/guides-glosa-badge.spec.ts`:**
```typescript
test('risk badge shown after TUSS select, guide linked on submit', async ({ page }) => {
  // Arrange: enable ai_glosa_prediction_enabled for test tenant via API/fixture
  await page.goto('/billing/guides/new?encounter=TEST_ID');
  await selectTussCode(page, '10101012');
  // badge loads (aria role=status present)
  await expect(page.getByRole('status')).toContainText(/Baixo risco|Risco médio|Alto risco/);
  await submitGuide(page);
  // Assert: new guide was created (redirect to guide detail page)
  // Verify prediction linked: GET /api/v1/billing/guides/{id}/ includes guide_id in metadata
  // OR: query /api/v1/ai/usage/ admin endpoint to confirm GlosaPrediction.guide set
});

test('no badge rendered when ai_glosa_prediction_enabled=False', async ({ page }) => {
  // Arrange: disable feature for test tenant
  await page.goto('/billing/guides/new');
  await selectTussCode(page, '10101012');
  await expect(page.getByRole('status')).not.toBeVisible();
});
```

---

## What This Sprint Does Not Include

- **SOAP Note AI Summarization** — deferred. Needs 3+ clinician interviews + CFM compliance
  review before any production deploy.
- **TUSS Table Update Checker (Celery Beat)** — P3, Sprint 10
- **AI analytics dashboard** — deferred until 30+ days of prediction outcome data
- **Per-tenant toggle via API/UI** — Django Admin is sufficient until second clinic onboards
- **WhatsApp integration** — Sprint 10
- **Prescription safety** — prescription signing stabilization required first
- **Fine-tuned glosa model** — Sprint 11+ (need 90 days of `was_denied` feedback data)

---

## Success Metrics

- **TUSSSyncLog:** ops can answer "TUSS last synced when?" from billing overview in < 3s
  (zero DB console queries needed)
- **TenantAIConfig:** enabling AI for clinic B does not affect clinic A (verified in test)
- **Glosa Prediction:** ≥ 1 high-risk prediction surfaced per week within first 30 days.
  Follow-up metric (90 days): correlation between predicted `high` risk and actual denial
  rate. Target: >60% precision on `high` predictions (i.e., predicted high → actually denied).

---

## Dependencies

- Sprint 8 merged on master (done: `5798196`)
- `LLMGateway` / `ClaudeGateway` in `apps/ai/gateway.py` (done)
- `TISSGuide.cid10_codes` JSONField (done, checked)
- `InsuranceProvider.ans_code` field (done)
- `TUSSCodeSearch` combobox component (done, Sprint 6b)
- `Glosa.reason_code` and `retorno_parser.py` (done, Sprint 6)
- Redis + Celery configured (Sprint 7)
- `ANTHROPIC_API_KEY` env var (Sprint 8)

---

## File Map

```
backend/apps/core/
  models.py           +TUSSSyncLog (SHARED_APPS / public schema — global TUSS log)
                      +TenantAIConfig (SHARED_APPS / public schema, FK to Tenant)
  admin.py            +TUSSSyncLogAdmin, +TenantAIConfigAdmin
  migrations/
    000N_tussynclog_tenantaiconfig.py
  management/commands/
    import_tuss.py    update: write TUSSSyncLog (start time, counts, status, error)

backend/apps/ai/
  models.py           +GlosaPrediction
  services.py         +get_tenant_ai_config(), +GlosaPredictor, +check_monthly_ceiling()
                       update TUSSCoder (per-tenant toggle/rate/ceiling/circuit)
  serializers.py      +GlosaPredictRequestSerializer, +GlosaPredictResponseSerializer
                      NOTE: TUSSSyncStatusSerializer → apps/core/serializers.py (not here)
  views.py            +GlosaPredictView
                      NOTE: TUSSSyncStatusView → apps/core/views.py (not here)
                       update TUSSSuggestFeedbackView: 200 not 404 when disabled
  urls.py             +/glosa-predict/
                      NOTE: /tuss-sync-status/ → apps/core/urls.py
  admin.py            +GlosaPredictionAdmin
  circuit_breaker.py  update: feature_key param on all functions
  rate_limiter.py     update: limit= param on is_rate_limited()
  migrations/
    0003_sprint9_glosaprediction.py
  management/commands/
    seed_prompt_templates.py    (new: idempotent AIPromptTemplate seeding)
  tests/
    test_tuss_sync_log.py               (new)
    test_tenant_ai_config.py            (new: includes Redis counter tests)
    test_glosa_predictor.py             (new)
    test_views_glosa.py                 (new: includes prediction→guide backlink)
    test_retorno_parser_feedback.py     (update: guide-level was_denied backfill)
    test_circuit_breaker.py             (update: feature_key isolation)
    test_rate_limiter.py                (update: per-tenant limit param)
    test_views.py                       (update: TUSSCoder uses TenantAIConfig)
    test_services.py                    (update: TUSSCoder uses TenantAIConfig)

backend/apps/billing/
  retorno_parser.py   update: backfill GlosaPrediction.was_denied (guide-level)
  serializers.py      update: guide create accepts glosa_prediction_ids (write-only)
  views.py            update: guide create view backlinks prediction IDs to guide

frontend/
  components/billing/
    GlosaRiskBadge.tsx          (new — full spec in S-034 section above)
  app/(dashboard)/
    billing/
      page.tsx                  update: TUSS DB sync badge (admin-only, secondary row)
      guides/new/page.tsx       update: GlosaRiskBadge per item row,
                                         track glosa_prediction_ids in form state
```

---

## Open Questions

**OQ-1: TenantAIConfig in tenant schema or public?**
RESOLVED (Eng review): Public schema, SHARED_APPS, FK to Tenant model.
Reasoning: Django Admin runs in public schema context; tenant-schema models crash or corrupt.
Standard django-tenants pattern for per-tenant config.

**OQ-2: Glosa Prediction — sync vs async?**
Sync (same pattern as TUSSCoder). Claude Haiku for short prompts (< 300 tokens) is ~300ms.
Circuit breaker + 5s timeout. Degrade silently on timeout.

**OQ-3: CID-10 on guide form — where does it come from?**
`TISSGuide.cid10_codes` is populated from the linked `encounter.soap_note.assessment`
on guide creation (already in the guide creation flow). The guide form has the insurer
(provider selector) and the encounter (prefilled from `?encounter=` query param).
The `GlosaRiskBadge` reads `cid10_codes` from the current form state.

**OQ-4: What if the tenant has no Glosa records yet (new clinic)?**
v1 is pure LLM zero-shot reasoning from ANS rules. Zero historical data needed.
Fine-tuned model with historical data is Sprint 11+.

---

## Architecture Diagram

```
PUBLIC SCHEMA (shared Django apps)
┌─────────────────────────────────────────────────────────┐
│ apps.core                                               │
│   TUSSSyncLog  (global TUSS import log)                 │
│     ran_at, status, row_counts, error_message           │
│          ▲                                              │
│   import_tuss cmd (apps/core/management/commands/)      │
│                                                         │
│   TenantAIConfig ──FK──► Tenant (django-tenants)       │
│     ai_tuss_enabled                                     │
│     ai_glosa_prediction_enabled                         │
│     rate_limit_per_hour                                 │
│     monthly_token_ceiling                               │
└───────────────────┬─────────────────────────────────────┘
                    │ get_tenant_ai_config(schema_name)
                    │ (cache 5min, Redis, public schema query)
                    ▼
TENANT SCHEMA (per-clinic)
┌─────────────────────────────────────────────────────────┐
│ apps.ai                          apps.billing           │
│                                                         │
│                                   TISSGuide             │
│                                     cid10_codes         │
│                                     provider ──►        │
│                                     items[]             │
│                                        ▲                │
│                                   guide create          │
│                                   serializer            │
│  GlosaPrediction ◄────────────── glosa_prediction_ids  │
│    tuss_code                      (write-only field)    │
│    insurer_ans_code                                     │
│    cid10_codes                                          │
│    risk_level / risk_reason        retorno_parser       │
│    guide ────────────────────────────────► was_denied   │
│    was_denied                     (guide-level match)   │
│         │                                               │
│         ▼                                               │
│  AIUsageLog                     InsuranceProvider       │
│    tokens_in/out                  name (sanitized       │
│    event_type                     before LLM inject)    │
│    created_at                     ans_code              │
│         │                                               │
│         ▼                                               │
│  Redis                                                  │
│    ai:config:{schema}        (TenantAIConfig cache)     │
│    ai:tuss:{schema}:{hash}   (TUSS suggest cache)       │
│    ai:glosa:{schema}:{hash}  (Glosa predict cache 24h)  │
│    ai:rl:{schema}:{hr}       (rate limit counter)       │
│    ai:cb:{schema}:tuss:*     (TUSS circuit breaker)     │
│    ai:cb:{schema}:glosa:*    (Glosa circuit breaker)    │
│    ai:tokens:{schema}:YYYY-MM (monthly token counter)   │
└─────────────────────────────────────────────────────────┘

EXTERNAL
┌─────────────────────────────────────────────────────────┐
│  Anthropic Claude Haiku API                             │
│    ← ClaudeGateway (LLMGateway interface)               │
│    Features: circuit breaker, 5s timeout, retry=0       │
│    TUSSCoder uses feature='tuss'                        │
│    GlosaPredictor uses feature='glosa'                  │
└─────────────────────────────────────────────────────────┘

FRONTEND
┌─────────────────────────────────────────────────────────┐
│  /billing/page.tsx                                      │
│    TUSS DB sync badge (admin-only, secondary row)       │
│    ← GET /api/v1/ai/tuss-sync-status/                   │
│                                                         │
│  /billing/guides/new/page.tsx                           │
│    GlosaRiskBadge per item row                          │
│    ← POST /api/v1/ai/glosa-predict/                     │
│    tracks glosa_prediction_ids in form state            │
│    → POST /api/v1/billing/guides/ (includes IDs)        │
└─────────────────────────────────────────────────────────┘
```

---

## Test Diagram

| Flow / Codepath | Test Type | File | Status |
|---|---|---|---|
| TUSSSyncLog model creates with correct fields | unit | test_tuss_sync_log.py | NEW |
| import_tuss writes TUSSSyncLog on success | integration | test_tuss_sync_log.py | NEW |
| import_tuss writes TUSSSyncLog on error (status='error') | integration | test_tuss_sync_log.py | NEW |
| TUSSSyncStatusView requires admin permission | unit | test_tuss_sync_log.py | NEW |
| TUSSSyncStatusView returns last_sync_age_days | unit | test_tuss_sync_log.py | NEW |
| TUSSSyncStatusView returns `partial` status correctly | unit | test_tuss_sync_log.py | NEW |
| TenantAIConfig in public schema (using='default') | unit | test_tenant_ai_config.py | NEW |
| get_tenant_ai_config cache hit | unit | test_tenant_ai_config.py | NEW |
| get_tenant_ai_config returns default (disabled) when no row | unit | test_tenant_ai_config.py | NEW |
| TUSSCoder.suggest() respects ai_tuss_enabled=False | unit | test_tenant_ai_config.py | NEW |
| TUSSCoder.suggest() respects per-tenant rate_limit_per_hour | unit | test_tenant_ai_config.py | NEW |
| monthly_token_ceiling blocks when exceeded (Redis counter) | unit | test_tenant_ai_config.py | NEW |
| monthly token Redis counter increments on AIUsageLog create | unit | test_tenant_ai_config.py | NEW |
| GlosaPredictor.predict() returns risk_level + reason | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor respects ai_glosa_prediction_enabled=False | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor respects per-tenant rate limiter | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor circuit breaker: tuss circuit independent from glosa | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor creates AIUsageLog entry | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor creates GlosaPrediction record | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor fail-open on LLMGatewayError | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor prompt injection guard on cid10 | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor prompt injection guard on insurer_name | unit | test_glosa_predictor.py | NEW |
| GlosaPredictor cache hit returns cached=True (24h TTL) | unit | test_glosa_predictor.py | NEW |
| GlosaPredictView requires billing.read permission | unit | test_views_glosa.py | NEW |
| GlosaPredictView returns degraded when feature disabled (not 404) | unit | test_views_glosa.py | NEW |
| GlosaPredictView returns 400 for invalid tuss_code_id | unit | test_views_glosa.py | NEW |
| Guide create: glosa_prediction_ids backlinks predictions to guide | integration | test_views_glosa.py | NEW |
| retorno_parser: was_denied backfill at guide level | integration | test_retorno_parser_feedback.py | UPDATE |
| circuit_breaker: feature_key='tuss' and 'glosa' are isolated | unit | test_circuit_breaker.py | UPDATE |
| rate_limiter: limit= param overrides global setting | unit | test_rate_limiter.py | UPDATE |
| TUSSSuggestFeedbackView: returns 200 (not 404) when feature disabled | unit | test_views.py | UPDATE |
| TUSSCoder uses TenantAIConfig instead of settings.FEATURE_AI_TUSS | unit | test_services.py | UPDATE |
| TUSSSyncStatusView: zero-rows returns never-synced state | unit | test_tuss_sync_log.py | NEW |
| TUSSSyncStatusView: non-admin user receives 403 | unit | test_tuss_sync_log.py | NEW |
| post_save signal: Tenant creation auto-creates TenantAIConfig row | unit | test_tenant_ai_config.py | NEW |
| monthly_token_ceiling: DB-seed on Redis miss (cold month start) | unit | test_tenant_ai_config.py | NEW |
| monthly_token_ceiling blocks GlosaPredictor (not just TUSSCoder) | unit | test_tenant_ai_config.py | NEW |
| GlosaPredictor cache TTL: key set with 24h timeout | unit | test_glosa_predictor.py | NEW |
| glosa_prediction_ids idempotency: already-linked IDs not re-linked | unit | test_views_glosa.py | NEW |
| retorno backfill: all GlosaPredictions for guide updated (not just first) | integration | test_retorno_parser_feedback.py | UPDATE |
| seed_prompt_templates: idempotent — second run creates no duplicates | unit | test_management_commands.py | NEW |
| GlosaRiskBadge: badge shown, guide linked on submit [→E2E] | e2e | guides-glosa-badge.spec.ts | NEW |
| GlosaRiskBadge: no badge when feature disabled [→E2E] | e2e | guides-glosa-badge.spec.ts | NEW |

---

## Failure Modes Registry

| Failure | Impact | Mitigation |
|---|---|---|
| `import_tuss` crashes mid-run | TUSSSyncLog.status='error', error_message set, badge turns red | Admin sees badge; rerun command |
| `TenantAIConfig` row missing for new tenant | `get_tenant_ai_config` returns default (all disabled) — AI silently off | On first login, default is correct behavior; admin enables via Django Admin |
| `GlosaPredictor` LLMGatewayError | circuit breaker records failure; fail-open returns `degraded=True` | Guide form still functional; badge absent |
| Anthropic API sustained outage | Circuit breaker opens after 3 failures (5-min cooldown) | All AI requests degrade silently; guide creation unaffected |
| `cid10_codes` empty on guide form | Badge renders informational grey pill "Diagnóstico não informado" | Faturista informed; no false prediction |
| `insurerId` null when adding items | GlosaRiskBadge suppresses fetch; no badge column rendered | Correct behavior; badge appears after insurer selected |
| Redis down during rate limit check | `is_rate_limited` fails open (returns False) — AI requests proceed | Existing pattern from Sprint 8; acceptable for pilot scale |
| Redis down during monthly ceiling check | `check_monthly_ceiling` seeds from DB on miss; if DB also fails, returns False | Extremely rare; acceptable fail-open |
| `glosa_prediction_ids` not passed on guide create | `GlosaPrediction.guide` remains null; `was_denied` backfill never fires | Data signal lost for that guide; model receives no feedback. Sprint 10 audit task |
| Insurer name contains prompt injection attempt | Newlines stripped, 100-char limit applied before LLM inject | Reduces attack surface to single-line bounded string |
| Simultaneous 10-item insurer change (rate exhaustion) | Rate limiter may block subsequent requests in same hour | Debounce on insurerId change; recommend rate_limit_per_hour >= 500 |
| `TUSSSyncLog.error_message` contains connection string | Scrubbed to 200 chars, pattern-stripped before storage | Admin API returns scrubbed message only |

---

## Decision Audit Trail

<!-- AUTONOMOUS DECISION LOG -->

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Rename "AI Expansion" → "AI Production Readiness + Glosa Prediction" | P5 Explicit | Prior framing hid that 2/3 stories are Sprint 8 cleanup | Keep misleading headline |
| 2 | CEO | S-033 TenantAIConfig → Django Admin only (no API/frontend) | P5, P3 | One clinic, second not yet onboarding; full API/UI is premature optimization | Full API + frontend page |
| 3 | CEO | Add monthly_token_ceiling field to TenantAIConfig | P2 Boil lakes | Cost modeling required before AI scales; easy to add now | Defer token tracking |
| 4 | CEO | S-034 → Glosa Prediction (user confirmed) | P1 Completeness | Revenue-protective + billing data moat; SOAP summary has no defensibility | SOAP summarization |
| 5 | CEO | Add `was_denied` backfill in retorno_parser | P2 Boil lakes | Closes feedback loop; retorno parser already processes denial records | Defer feedback loop |
| 6 | CEO | GlosaPrediction fail-open (degraded=true, not error) | P5 Explicit | Guide creation must never block on AI failure | Fail closed |
| 7 | CEO | Success metric: 60% precision on high-risk predictions (90-day) | P1 Completeness | "10 summaries in first week" is vanity metric; precision measures actual value | Clicks-only metric |
| 8 | CEO | Prompt injection guard on CID-10 input | P5, Security | CID-10 from form input; strip non-alphanumeric before LLM inject | Trust form input |
| 9 | Design | Badge column: immediately after TUSS code, fixed w-28 | P5 Explicit | Default (last column) causes post-commitment alarm; early placement enables pre-commit decision | Last column |
| 10 | Design | Loading = skeleton shimmer (not spinner) | P5 Explicit | Prevents visual collision with TUSSSuggestionInline spinner in same row | Spinner |
| 11 | Design | Guard: no fetch when insurerId=null | P5 Explicit | Bad prediction without insurer; empty column looks broken | Fire anyway |
| 12 | Design | Guard: no fetch when cid10Codes empty; show info pill | P5 Explicit | Empty CID-10 = unreliable prediction; info pill explains gap | Suppress silently |
| 13 | Design | Add `error` state (grey "Risco indisponível") | P1 Completeness | Infrastructure failure ≠ feature disabled; conflating them masks API errors | Collapse into degraded |
| 14 | Design | Map `partial` sync status → yellow on TUSS DB badge | P1 Completeness | Partial sync = incomplete TUSS table; time-based color would mislead to green | Ignore partial status |
| 15 | Design | TUSS DB badge: secondary row below h1, right-aligned, min-h reserved | P5 Explicit | Layout shift for admin vs non-admin users if no height reservation | Inline in KPI cards |
| 16 | Design | Badge colors: bg-*-100 not bg-*-50 | P5 Explicit | `-50` fails AA contrast at text-xs; `-100` matches existing DESIGN.md badge recipe | bg-*-50 as planned |
| 17 | Design | Tooltip: shadcn Tooltip, max-w-xs, hover+focus, role=tooltip | P1 Completeness | Native title= not WCAG 2.1 AA compliant; keyboard nav required | title= attribute only |
| 18 | Design | High/medium tooltip includes action hint | P1 Completeness | "Alto risco" without actionability creates anxiety; faturista needs next step | risk_reason only |
| 19 | Design | Low risk badge has tooltip (confirmatory) | P2 Boil lakes | Inert badge trains distrust; tooltip confirms system is alive | No tooltip on low risk |
| 20 | Design | Dismissal signal: has_dismissed_high_risk on guide submit | P2 Boil lakes | Without override signal, model learns only from retorno; false-positive rate grows unchecked | Defer signal collection |
| 21 | Design | aria-live="polite" + role="status" on badge container | P1 Completeness | Screen readers won't announce state change without aria-live | Implicit announcement |
| 22 | Design | aria-label on TUSS DB sync badge (status + human-readable) | P1 Completeness | Color-only status is not accessible | No aria-label |
| 23 | Design | Low risk: bg-gray-100 text-gray-600 (matches draft guide status) | P5 Explicit | "grey" was undefined; pattern-match to existing DESIGN.md recipe | Implementer picks |
| 24 | Eng | TenantAIConfig → SHARED_APPS / public schema, FK to Tenant | P5 Critical | Tenant-schema model in Django Admin = crash or cross-schema corruption | Tenant schema model |
| 25 | Eng | Monthly token ceiling → Redis counter (not DB aggregate) | P5, P3 | Per-call DB aggregate becomes full table scan; Redis counter = O(1) | DB aggregate on every call |
| 26 | Eng | Retorno backfill: guide-level match only (not tuss_code+guide) | P3 Pragmatic | TISS 4.01.00 retorno XML has no tuss_code in glosa elements — item-level match impossible | Item-level matching |
| 27 | Eng | Dismissal signal (has_dismissed_high_risk) → deferred to Sprint 10 | P3 Pragmatic | No viable implementation path (null guide_id at prediction time, complex through-table) | Half-implement in Sprint 9 |
| 28 | Eng | Prediction-to-guide linking: pass glosa_prediction_ids in guide create payload | P1 Completeness | Without linking, GlosaPrediction.guide=null forever; backfill never fires | Defer linking |
| 29 | Eng | rate_limiter.is_rate_limited() accepts per-tenant limit param | P2 Boil lakes | rate_limit_per_hour field was dead (rate_limiter.py read global settings only) | Dead field |
| 30 | Eng | Circuit breaker keys include feature name (tuss vs glosa) | P5 Explicit | Shared circuit: glosa prompt failure disables TUSS suggestions for same tenant | One circuit per tenant |
| 31 | Eng | Cache TTL 24h (not 7 days); use full SHA256 digest | P5 Explicit | 7-day stale false-negatives on insurer rule changes; 16-char truncation collision risk | 7-day TTL, truncated key |
| 32 | Eng | InsuranceProvider.name sanitized before LLM inject | P5, Security | User-editable CharField can contain prompt injection via newlines | "from DB = safe" |
| 33 | Eng | Prompt templates seeded via management command, not migration | P5 Explicit | RunPython in tenant migrations = fragile multi-tenant deployment | Migration data seed |
| 34 | Eng | Insurer change re-debounces all item rows simultaneously | P5 Explicit | 10-item guide + insurer change = 10 simultaneous requests, exhausts rate limit | Per-row debounce only |
| 35 | Eng | TUSSSuggestFeedbackView: 200 not 404 when feature disabled | P2 Boil lakes | 404 silently drops feedback when feature toggled; 200 with detail message preserves intent | Keep 404 |
| 36 | Eng | TUSSSyncLog.error_message scrubbed (strip conn strings, 200 char limit) | P5 Explicit | Admin API could leak infrastructure details via exception string | Raw exception storage |
| 37 | Codex | post_save signal auto-creates TenantAIConfig on Tenant creation | P2 Boil lakes | "Fallback to all disabled if no row" is indistinguishable from zero adoption; explicit row is visible in Admin | Silent fallback only |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/autoplan` | Scope & strategy | 1 | CLEAR (PLAN via /autoplan) | 10 findings — all resolved. Strategic pivot: SOAP summary → Glosa Prediction (user-gated). |
| Design Review | `/autoplan` | UI/UX gaps | 1 | CLEAR (PLAN via /autoplan) | 18 findings, score 3/10 → 8/10. 4 critical fixed in spec. |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR (PLAN) | Run 1 (autoplan): 13 issues. Run 2 (standalone 2026-04-02): 12 issues — 6 critical fixed: TUSSSyncLog wrong schema (moved to apps.core), dismissal signal stale spec removed, missing template handling, Glosa global kill switch, existing-tenant backfill, CID-10 debounce trigger. 6 test gaps added. 2 TODOS added. |
| Codex Review | `/plan-eng-review` | Outside voice | 2 | issues_found → all resolved | Run 1 (autoplan): 12 findings, 1 net-new (Decision 37). Run 2 (standalone): 19 findings — 8 actionable resolved (rate limit default 100→500, orphan cleanup Celery task, Glosa kill switch, backfill for existing tenants, AppConfig.ready() note, CID-10 re-debounce, E2E spec fix, missing template handling). 3 deferred to TODOS. |

**UNRESOLVED:** 0

**VERDICT:** APPROVED — 2 full eng review passes. All critical gaps resolved. 50 total decisions across CEO + Design + Eng + Codex reviews. Plan is implementation-ready.

**Next step:** Create `feature/sprint9-ai-expansion` branch and run `/ship` when implementation complete.
