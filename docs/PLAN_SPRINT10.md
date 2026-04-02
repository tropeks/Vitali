<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260402-105042.md -->
# Sprint 10 — Billing Intelligence Dashboard

**Status:** DRAFT — CEO review complete, Design + Eng review in progress
**Date:** 2026-04-02
**Branch:** feature/sprint10-billing-intelligence
**Epics:** E-013 (Billing Analytics), E-014 (Glosa Accuracy Tracker), E-015 (TUSS Staleness Monitor)
**Target user:** Faturista (billing clerk) — task-oriented, not dashboard-first
**Success metric:** Billing analytics page opened ≥1x/week by pilot clinic within 30 days of launch

---

## Context

Sprint 9 shipped AI production readiness: TUSSSyncLog, TenantAIConfig, and Glosa Prediction.
The AI layer now collects data — every guide creation generates a GlosaPrediction record;
every retorno backfills `was_denied`.

But clinic owners have zero visibility into that data. They also have zero visibility into
billing health overall. The billing overview page (`/billing`) shows a basic guide list and
open batches. There are no aggregate metrics, no trend charts, no denial rate tracking.

The analytics app (`apps.analytics`) covers EMR metrics (appointments, wait times,
patient growth) but is completely blind to billing. recharts is already installed.

Sprint 10 closes this gap: **billing becomes measurable**.

Three stories:

1. **S-035 — Billing Analytics API**: 5 aggregate endpoints covering monthly revenue,
   denial rate by insurer, guide status distribution, and batch throughput.

2. **S-036 — Billing Intelligence Page**: New `/billing/analytics` frontend page with
   recharts charts, KPI cards, and period filtering. Includes S-037 Glosa Accuracy section.

3. **S-037 — Glosa Prediction Accuracy Tracker**: Single endpoint surfacing
   prediction precision and recall per insurer from `GlosaPrediction.was_denied` data.
   Rendered as a table on the analytics page.

4. **S-038 — TUSS Staleness Monitor**: Celery Beat periodic task that checks
   `TUSSSyncLog` age and logs a structured warning if TUSS data is older than 30 days.
   Extends import_tuss to register a Beat schedule on first successful sync.

---

## Stories

### S-035 — Billing Analytics API

**Acceptance criteria:**
- `GET /api/v1/analytics/billing/overview/` returns:
  ```json
  {
    "period": "2026-04",
    "total_billed": 45200.00,
    "total_collected": 32000.00,
    "total_denied": 4800.00,
    "denial_rate": 0.106,
    "guides_total": 48,
    "guides_submitted": 30,
    "guides_paid": 22,
    "guides_denied": 5,
    "guides_draft_pending": 13
  }
  ```
- `GET /api/v1/analytics/billing/monthly-revenue/?months=6` returns list of 6 monthly buckets with `period`, `billed`, `collected`, `denied`
- `GET /api/v1/analytics/billing/denial-by-insurer/?months=6` returns insurer breakdown: `insurer_name`, `total_guides`, `denied_guides`, `denial_rate`, `denied_value` — **excludes insurers with fewer than 10 submitted guides**; sorted by `denied_value DESC`
- `GET /api/v1/analytics/billing/batch-throughput/?months=6` returns monthly batch creation + closure counts
- `GET /api/v1/analytics/billing/glosa-accuracy/` returns prediction accuracy per insurer (S-037)
- All endpoints require `IsAuthenticated`. No new permission required (billing.read exists).
- All aggregate on current tenant's schema data only.

**Backend files:**
- `backend/apps/analytics/views.py` — add 5 new APIViews
- `backend/apps/analytics/urls.py` — add 5 new paths under `billing/`
- `backend/apps/analytics/serializers.py` — create (new file) with DRF response serializers for all 5 billing endpoints (explicit field definitions for future OpenAPI/Swagger generation)

**Query approach:**
- Monthly revenue grouping: group on `TISSGuide.competency` (CharField format `"AAAA-MM"`) NOT on `TruncMonth('created_at')`. Use `.values('competency').annotate(...)` sorted by `competency`. Reason: `competency` is the TISS accounting period; `created_at` is guide draft date — a February guide drafted in March must appear in February's bucket.
- `total_collected` = `Sum('total_value', filter=Q(status='paid'))` — guides with `status='paid'` only
- `total_denied` = `Sum('total_value', filter=Q(status__in=['denied', 'appeal']))` — appeal-status guides count as denied for financial exposure reporting
- `total_billed` = `Sum('total_value')` — all guides regardless of status
- Denial rate denominator = `Count(id, filter=Q(status__in=['submitted','paid','denied','appeal']))` — excludes drafts and pending-send. NOT `Count(id)` (which includes drafts and understates the rate).
- `denied_value` in denial-by-insurer = `Sum('total_value', filter=Q(status__in=['denied','appeal']))` — guide-level financial exposure (NOT `Glosa.value_denied`)
- Denial-by-insurer volume floor: exclude insurers with fewer than 10 non-draft guides: `filter=Q(status__in=['submitted','paid','denied','appeal'])`. "Submitted" alone is wrong — paid/denied guides are no longer in submitted status.
- Denial-by-insurer ORM path: `.values('provider_id', 'provider__name', 'provider__ans_code')` — no separate `InsuranceProvider` import needed
- Glosa accuracy: `GlosaPrediction.objects.filter(guide__isnull=False).values('insurer_ans_code').annotate(total=Count('id', filter=Q(was_denied__isnull=False)), predicted_high=Count('id', filter=Q(risk_level='high')), was_denied=Count('id', filter=Q(was_denied=True)), true_positives=Count('id', filter=Q(risk_level='high', was_denied=True)))` — `total` counts only resolved predictions (`was_denied__isnull=False`); unresolved (`was_denied=None`) are excluded from denominator
- When `predicted_high = 0`: return `{"precision": null}` not ZeroDivisionError
- For DenialByInsurerView: traverse via `.values('provider_id', 'provider__name', 'provider__ans_code')` — single JOIN query, no separate import
- For GlosaAccuracyView: GlosaPrediction stores `insurer_ans_code` as CharField with no FK to InsuranceProvider. After aggregation, resolve names with one extra query: `insurer_names = dict(InsuranceProvider.objects.values_list('ans_code', 'name'))`, then per row: `insurer_name = insurer_names.get(row['insurer_ans_code'], row['insurer_ans_code'])`. Two queries total — not N+1.

**Performance:**
- All endpoints hit DB once (single aggregated query per endpoint)
- No N+1 risk
- Add `select_related` where joining insurer name
- No cache layer at this stage — single-pass aggregate queries are fast enough at pilot scale. Add cache when tenant count exceeds 10. (`# TODO: cache with key ai:billing_analytics:{schema}:{endpoint}:{period} when N>10 tenants`)

**Tests:**
- `backend/apps/analytics/tests/test_billing_analytics.py` (new)
- 1 happy path per endpoint (5 tests)
- 1 empty state per endpoint (returns zeroed structure, not 404)
- 1 unauthenticated returns 401
- `test_appeal_status_counted_in_total_denied` — guides with `status='appeal'` appear in `total_denied`
- `test_denial_rate_excludes_draft_guides` — draft guides not in denominator
- `test_collected_field_uses_paid_status_only` — `total_collected` = paid-status guide sum only
- `test_monthly_revenue_groups_by_competency` — February guide drafted in March appears in February bucket
- `test_insurer_below_10_guide_floor_excluded` — insurer with 9 non-draft guides not in denial chart
- `test_insurer_volume_floor_counts_non_draft_statuses` — paid/denied guides count toward floor (not just status='submitted')
- `test_glosa_accuracy_precision_null_when_no_high_risk` — precision=null returned when predicted_high=0
- `test_glosa_accuracy_excludes_unresolved_from_denominator` — was_denied=None excluded from total
- `test_glosa_accuracy_recall_calculation`
- `test_denial_by_insurer_sorted_by_denied_value_desc`
- `test_denial_rate_zero_when_no_submitted_guides` — zero submitted/paid/denied/appeal guides → denial_rate=0.0, not ZeroDivisionError
- `test_monthly_revenue_months_param_clamped` — `?months=0` and `?months=200` handled gracefully (clamp to valid range, e.g. min=1 max=24)
- `test_batch_throughput_cross_month_merge_correctness` — batch created Jan, closed Mar → appears in Jan's created_count AND Mar's closed_count (not both in Jan)
- Total: ~25 tests

---

### S-036 — Billing Intelligence Page

**Acceptance criteria:**

**Layout / information hierarchy (task-oriented order):**
- New page at `/billing/analytics`
- Sidebar nav: add "Análise" as a **flat peer nav item** under the Faturamento section label (same indentation as existing "Faturamento" link — NOT an accordion child; no expandable group)
- Page order top-to-bottom: (1) KPI cards, (2) Denial by insurer chart, (3) Revenue trend chart, (4) Batch throughput chart, (5) Glosa AI Accuracy section — this puts the actionable item (denial) above the contextual item (revenue trend)

**KPI cards:**
- Row: Taxa de Glosa and Total Glosado first (problem indicators), then Total Faturado, Total Pago — always shows current-month data, labeled "Mês atual"
- KPI cards are **always locked to current month** regardless of the period toggle. The period toggle does NOT affect KPI cards. KPI card components do not receive a `months` prop.
- Zero state: show "R$ 0,00" (not hidden, not "—")
- KPI grid: `grid-cols-2 xl:grid-cols-4` (responsive)

**Charts:**
- Revenue trend chart: AreaChart (recharts), default 6 months; chart green area = `Não Glosado` = total_billed - total_denied (this DIFFERS from the KPI card "Total Pago" which = paid-status guides only — submitted/pending guides are in the green area but not yet paid; label the chart area "Não Glosado" not "Recebido" to avoid visual contradiction with the KPI card); appeal-status guides are counted in `total_denied` (i.e. query uses `Q(status__in=['denied', 'appeal'])`); areas are `não_glosado` (green) and `glosado` (red) stacked to total_billed — NOT additive
- Denial by insurer chart: BarChart (recharts), top 5 insurers ranked by `denied_value DESC` (not denial rate), **minimum 10 submitted guides required to appear** (insurers with <10 guides are excluded from the chart); horizontal bars; `barSize={44}` minimum for touch targets; **clicking a bar navigates to `/billing/guides?status=denied&provider={ans_code}`** (action hook — addresses CEO finding); bars must be keyboard-focusable: `tabIndex={0}` + `onKeyDown` handler for Enter/Space
- Batch throughput chart: LineChart (recharts), created vs closed per month; backend uses two separate queries merged in Python: `TruncMonth('created_at')` for created series, `TruncMonth('closed_at')` for closed series (only batches where `closed_at__isnull=False`). Merge by month key in view before returning response. Reason: a batch created in January and closed in March must appear in January's created count AND March's closed count — single-query grouping gets this wrong.
- Period selector: `3m / 6m / 12m` toggle, default=**6m**, updates charts only (not KPI cards); rendered as `role="group"` with three `<button>` elements; during period-change fetches, chart areas show `animate-pulse` overlay (not full page skeleton); period selector is `flex-wrap` at small breakpoints

**Glosa AI Accuracy section:**
- If zero predictions exist: show section header + onboarding copy "A IA de Glosa está aprendendo. Acompanhe a precisão após 10 previsões por convênio." pointing to guide creation flow — do NOT hide the section silently
- If predictions exist but no insurer has ≥10 yet: show progress indicator per insurer (e.g. "Unimed: 3/10 previsões")
- If ≥10 predictions for an insurer: show table with columns insurer, total predictions, high-risk %, actual denial %, precision
- Precision cell: show "—" when `predicted_high = 0` for an insurer (API returns `null`, frontend renders "—")
- Sort table by `was_denied DESC`

**States:**
- Initial loading state: skeleton cards and chart placeholders (while first fetch is in-flight)
- Empty state (data returned, zero records): `<p className="text-sm text-gray-400 text-center py-6">Sem dados para o período</p>` — NOT a skeleton
- Error state (any endpoint returns 5xx or times out): render per-section error banner using DESIGN.md alert pattern (`bg-red-50 border-red-200 text-red-700`); copy: "Não foi possível carregar os dados. Tente novamente." with ghost-button retry that re-fires only the failed request. A failed endpoint does NOT crash the whole page.
- "Dados insuficientes" copy is reserved ONLY for S-037 statistical threshold guard (<10 predictions). All other empty states use "Sem dados para o período".

**Accessibility:**
- KPI cards: `aria-label="Taxa de Glosa: 10,6% no mês atual"` pattern
- Period toggle: three `<button>` elements inside a `role="group"` wrapper
- Denial chart bars: `tabIndex={0}` + `onKeyDown` for Enter/Space navigation

**Frontend files:**
- `frontend/app/(dashboard)/billing/analytics/page.tsx` (new, ~200 lines — page shell, data fetching, layout)
- `frontend/components/billing/BillingKPICard.tsx` (new, simple card with aria-label)
- `frontend/components/billing/RevenueChart.tsx` (new, recharts AreaChart)
- `frontend/components/billing/DenialByInsurerChart.tsx` (new, recharts BarChart with keyboard nav)
- `frontend/components/billing/BatchThroughputChart.tsx` (new, recharts LineChart)
- `frontend/components/billing/GlosaAccuracyTable.tsx` (new, table + cold-start state + progress indicators)
- `frontend/components/layout/DashboardShell.tsx` — add "Análise" flat peer nav item

**Design system:**
- Charts follow DESIGN.md color palette: `green-500` (`#22c55e`) for collected (NOT emerald-500 `#10b981`), denial area fill `fill` uses `red-200` with `stroke` `red-500`, blue (`#3b82f6`) for neutral
- Cards use same `bg-white rounded-xl border border-gray-200 p-5` pattern as billing overview
- Empty states use `text-gray-400 text-sm text-center py-6` pattern

---

### S-037 — Glosa Prediction Accuracy Tracker

Included in S-035 endpoint + S-036 page. No separate files beyond what those stories need.

**Additional acceptance criteria:**
- If fewer than 10 predictions exist for an insurer, show progress indicator ("Unimed: 3/10 previsões") instead of accuracy stats
- Accuracy metrics: precision = true_positives / predicted_high; recall = true_positives / was_denied. Both rounded to 1 decimal %.
- **When `predicted_high = 0` for an insurer: API returns `null` for precision (not ZeroDivisionError). Frontend renders "—" in precision cell.**
- Sort table by `was_denied DESC` (most denied insurer first)

---

### S-038 — TUSS Staleness Monitor

**Acceptance criteria:**
- Celery Beat periodic task `check_tuss_staleness` registered in `CELERY_BEAT_SCHEDULE` (settings)
- Runs daily at 08:00 UTC
- Checks `TUSSSyncLog.objects.using('default').filter(status='success').order_by('-ran_at').first()`
- If most recent success is older than 30 days (or no successful sync exists): logs `WARNING apps.ai.tasks TUSS data is stale: last_sync={date}, age_days={N}. Run: python manage.py import_tuss`
- If last sync is between 14-29 days: logs `INFO apps.ai.tasks TUSS data is ageing: age_days={N}`
- Under 14 days: no log
- No external notifications (email/Slack) in Sprint 10 — logs only. Notifications are Sprint 11+.
- Task is fail-safe: any DB exception → logs error and exits cleanly (never raises)

**Backend files:**
- `backend/apps/ai/tasks.py` — add `check_tuss_staleness` task
- `backend/vitali/settings/base.py` — add to `CELERY_BEAT_SCHEDULE` dict
- `backend/apps/ai/migrations/XXXX_schedule_celery_beat_tasks.py` (new data migration) — creates **two** `PeriodicTask` rows in `django_celery_beat`: (1) `check_tuss_staleness` daily at 08:00 UTC, (2) `cleanup_orphaned_glosa_predictions` daily at 02:00 UTC. Reason: `DatabaseScheduler` reads from DB; the settings dict alone is insufficient. Note: `cleanup_orphaned_glosa_predictions` was defined in Sprint 9 but never registered — fixing both in one migration. Migration must use `RunPython` with `apps` parameter to get `PeriodicTask` model from `django_celery_beat`. **Idempotency required:** use `PeriodicTask.objects.get_or_create(name='...', defaults={...})` not `.create()` — migration must be safe to run on a DB that already has these rows.

**Tests:**
- `backend/apps/ai/tests/test_tasks.py` (new or extend existing)
- Test: stale (>30d) logs WARNING
- Test: ageing (14-29d) logs INFO
- Test: fresh (<14d) no log
- Test: no syncs ever → logs WARNING
- Test: DB error → no exception raised

---

## What is NOT in scope

- Email/Slack notifications for TUSS staleness (Sprint 11+)
- Batch Glosa Prediction endpoint (`/ai/glosa-predict-batch/`) — still P3, deferred
- Per-item denial label accuracy improvement — blocked by ANS TISS spec (Sprint 11+)
- Export to PDF/CSV — Sprint 11+
- Multi-tenant analytics comparison (admin super-view across tenants) — out of scope for clinic-level SaaS
- Recharts SSR warnings — cosmetic, not blocking

---

## What Already Exists

| Sub-problem | Existing code |
|-------------|---------------|
| Billing data aggregation | `apps.billing` — TISSGuide, TISSBatch, Glosa models with status fields |
| Analytics infrastructure | `apps.analytics.views` — OverviewView, TruncMonth, Count, Q patterns |
| Tenant-aware queries | All views use authenticated request, django-tenants auto-routes |
| recharts | `frontend/package.json` — `recharts: ^2.13` |
| KPI card pattern | `billing/page.tsx` — same card pattern, can copy |
| Auth/permission pattern | All analytics views use `IsAuthenticated` |
| GlosaPrediction data | `apps.ai.models.GlosaPrediction` — `was_denied`, `risk_level`, `insurer_ans_code` |
| TUSSSyncLog | `apps.core.models.TUSSSyncLog` — `ran_at`, `status`, from Sprint 9 |
| Celery Beat | Already configured in settings for `cleanup_orphaned_glosa_predictions` |

---

## Migration Plan

One migration required — **S-038 Celery Beat task registration**:

- `backend/apps/ai/migrations/XXXX_schedule_celery_beat_tasks.py` — data migration using `RunPython` to create `PeriodicTask` rows for `check_tuss_staleness` and `cleanup_orphaned_glosa_predictions` in `django_celery_beat`. Uses `get_or_create` for idempotency.

No schema changes (no new model fields or tables). All billing endpoints are read-only aggregate queries on existing tables.

---

## Test Coverage Target

| Story | Test file | Count |
|-------|-----------|-------|
| S-035 | `apps/analytics/tests/test_billing_analytics.py` | ~15 |
| S-038 | `apps/ai/tests/test_tasks.py` | ~5 |
| S-036/037 | Frontend — no test framework set up; visual QA | 0 |
| **Total** | | ~20 new tests |

---

## CEO Review — Key Decisions

**Decision A: Add action hook to denial chart (CEO gate)**
User confirmed. Denial-by-insurer chart clicking navigates to filtered guide list. Addresses both CEO voices' "visibility without actuation" finding.

**Decision B: Remove analytics cache layer (auto-decided, P5)**
Redis caching for aggregate analytics endpoints adds operational complexity with no measurable benefit at 1-clinic scale. Add TODO comment for when N>10 tenants.

**Decision C: Target user is faturista, not clinic owner (auto-decided, P4)**
Plan originally said "clinic owners have zero visibility." The actual user of billing tools in Brazilian SME healthcare is the faturista (billing clerk). Plan text updated.

**Decision D: recharts stacking fix (auto-decided, P5)**
Plan said "stacked collected + denied areas" which would show billed+denied (double-counting). Correct formula: collected = total_billed - total_denied.

**Decision E: S-037 threshold guard retained (auto-decided, P1)**
"Dados insuficientes" guard for <10 predictions per insurer already in plan. The AI accuracy table is low-effort; the cold-start guard is sufficient mitigation for empty state.

---

## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | apps.analytics home for billing views | P5 (explicit) | analytics app is explicitly for analytics; billing model import is not coupling | New app (over-engineered) |
| 2 | CEO | Remove cache layer | P5 (explicit) | 1-clinic pilot; aggregate queries are fast; avoids stale-read complexity | 5-min Redis cache |
| 3 | CEO | Add click-to-filter action on denial chart | P1 (completeness) | User confirmed; closes actuation gap both CEO voices flagged | Read-only chart |
| 4 | CEO | recharts stacking = collected + denied (not additive) | P5 (explicit) | collected = total_billed - total_denied prevents visual double-counting | Additive stacked area |
| 5 | CEO | S-037 kept with <10 guard | P1 (completeness) | Low effort; cold-start guard sufficient | Drop S-037 entirely |
| 6 | Design | KPI cards locked to current month (2-voice confirmed) | P5 (explicit) | Period toggle controls charts only; KPI cards labeled "Mês atual"; prevents source-of-truth conflict flagged independently by both design voices | KPI cards update with toggle |
| 7 | Design | Denial chart: min 10 guides filter + rank by denied_value | P1 (completeness) | 1-guide insurer at 100% rate dominates chart; money = actuation signal, rate alone misleads | Naive top-5-by-rate |
| 8 | Design | precision = null when predicted_high = 0 (API contract) | P5 (explicit) | ZeroDivisionError on live endpoint; frontend renders "—" | Raise exception or return 0 |
| 9 | Design | Information hierarchy: denial chart 2nd, revenue trend 3rd | P4 (user) | Faturista is task-oriented; actionable item (denial by insurer) before contextual item (trend) | KPI → trend → denial order |
| 10 | Design | Error state: per-section with retry, not page-level crash | P1 (completeness) | 5 independent endpoints; one 500 should not blank the page | No error state |
| 11 | Design | Sidebar nav "Análise" as flat peer item (no accordion) | P5 (explicit) | No accordion pattern in existing nav; avoid structural DashboardShell refactor | Expandable accordion group |
| 12 | Design | appeal-status guides counted in total_denied (stacking) | P5 (explicit) | Visual stacking must account for contested guides; explicit query filter Q(status__in=['denied','appeal']) | Exclude appeal-status |
| 13 | Design | Color: green-500 (#22c55e) not emerald-500 (#10b981) | P5 (explicit) | DESIGN.md Analytics section specifies green-500; emerald is visually different and not in the system | Keep #10b981 |

---

## Design Review — Key Decisions

**D1: KPI cards locked to current month (2-voice confirmed)**
Both Claude and Codex independently flagged the period toggle / KPI card source-of-truth conflict. Resolution: KPI cards are always "Mês atual," exempt from the period toggle. Charts-only filter.

**D2: Denial chart minimum volume floor**
Top-5 by rate without a volume floor means 1 denied guide out of 1 = 100% rate, dominating the chart. Fixed: minimum 10 submitted guides to appear; ranked by `denied_value DESC` (money is the actuation signal).

**D3: ZeroDivisionError guard in precision (auto-decided)**
When `predicted_high = 0`, API returns `null` for precision. Frontend renders "—". Prevents 500 on live endpoint.

**D4: Information hierarchy reorder (auto-decided)**
Faturista is task-oriented. Denial by insurer (actionable) moved to 2nd position, above revenue trend (contextual). KPI leads, then action, then context.

**D5: Error state added to S-036 (auto-decided)**
Per-section error banners with retry. No page-level crash on a single failed endpoint.

**D6: AI accuracy section never hidden silently (auto-decided)**
New clinics see onboarding copy + progress indicators rather than an invisible section. Fixes the cold-start adoption cliff.

---

## Eng Review — Key Decisions

**E1: `total_collected` defined as Sum(total_value, status='paid') (auto-decided, blocker)**
No payment-received field exists in `TISSGuide`. `total_collected` = paid-status guides only. Chart "collected" area = `total_billed - total_denied` (visual formula, not DB field) — these two differ intentionally: the KPI card shows confirmed payments; the chart shows the "not-denied" zone.

**E2: `denied_value` defined as Sum(total_value, status in denied+appeal) (auto-decided, blocker)**
Guide-level financial exposure, not line-item `Glosa.value_denied`. This is the total the insurer refused, which is what drives the faturista's action.

**E3: Monthly revenue groups by `competency` CharField not `TruncMonth(created_at)` (auto-decided, high)**
`competency` is the TISS accounting period. `TruncMonth` on a CharField crashes. Group on `.values('competency')` and sort alphabetically (format `AAAA-MM` sorts correctly as a string).

**E4: `was_denied=None` excluded from glosa accuracy denominator (auto-decided, high)**
Unresolved predictions inflate the denominator and make precision/recall meaningless. `total` = count of predictions where `was_denied__isnull=False`.

**E5: Denial chart volume floor uses `status__in=['submitted','paid','denied','appeal']` (auto-decided, high)**
"10 submitted guides" was ambiguous. Paid/denied guides are no longer in `submitted` status — the correct floor is all non-draft guides.

**E6: S-038 requires data migration for `PeriodicTask` record (auto-decided, medium)**
`DatabaseScheduler` ignores `CELERY_BEAT_SCHEDULE` settings dict if the DB record doesn't exist. A data migration creates the `PeriodicTask` entry reliably on deploy.

**E7: `denial_rate` denominator excludes drafts (auto-decided, medium)**
`Count(id)` with drafts understates denial rate by including guides that never entered the TISS cycle. Denominator = submitted+paid+denied+appeal.


## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 2 | CLEAR | 5 decisions applied (action hook, cache removed, stacking fix, user target, S-037 guard) |
| Design Review | `/plan-design-review` | UI/UX gaps | 2 voices | CLEAR | 12 findings applied; info hierarchy reordered, error states, color tokens, period toggle, cold-start |
| Eng Review | `/plan-eng-review` | Architecture & tests | 3 | CLEAR | 9 issues; serializers added, Beat migration fixed, batch throughput query specified, 30 tests, idempotency guard, Migration Plan corrected, "collected" label fixed |
| Outside Voice | Claude subagent (Opus) | Independent 2nd opinion | 1 | issues_found | 5 findings; Migration Plan contradiction fixed, "collected" label fixed; 2 informational (ans_code fallback, telemetry) |

**VERDICT:** CLEARED — All blockers resolved. 30 backend tests specified. Plan approved for build. Branch: `feature/sprint10-billing-intelligence`.
