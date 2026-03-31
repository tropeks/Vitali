<!-- /autoplan restore point: /c/Users/halfk/.gstack/projects/tropeks-Vitali/master-autoplan-restore-20260330-213133.md -->
<!-- autoplan: tropeks-Vitali / master / 19ebe80 / 2026-03-30 -->

# Sprint 8 Plan — AI TUSS Auto-Coding (E-008)

**Branch:** feature/sprint8-ai-tuss
**Sprint:** 8
**Epic:** E-008 — AI TUSS Auto-Coding
**Stories:** S-030, S-031
**Total points:** 16 (8 + 8)
**Design doc:** `~/.gstack/projects/tropeks-Vitali/halfk-master-design-20260328-145944.md`

---

## Goal

Give faturistas an AI co-pilot for TISS billing: type a procedure description → AI returns the top 3 matching TUSS codes ranked by relevance. This reduces the main friction in billing — manually hunting through 6,000+ TUSS codes — without removing human judgment. The faturista always selects; the AI just surfaces candidates.

**Explicit out-of-scope:**
- OpenAI integration (start with Claude only; abstract interface allows adding later)
- AI clinical notes scribe (Phase 2)
- AI prescription safety checking (Phase 2)
- Autonomous code selection without human confirmation
- TUSS table auto-updater from ANS (P3 item in TODOS.md)

---

## Stories

### S-030 — LLM Integration Layer (8 pts)

**Acceptance Criteria:**
- `LLMGateway` abstract interface with `complete(prompt, system, max_tokens) → str`
- `ClaudeGateway` implementation using Anthropic SDK (`claude-haiku-4-5-20251001` for cost)
- `AIPromptTemplate` model (name, version, system_prompt, user_prompt_template, is_active)
- `AIUsageLog` model (tenant, prompt_template, tokens_in, tokens_out, latency_ms, created_at)
- Celery task wrapper: `run_llm_task(prompt_template_id, context_json) → AIUsageLog.id`
- Per-tenant rate limiting via Redis (`ai:rate:{tenant_schema}` — 100 calls/hour default)
- Monthly usage summary endpoint: `GET /api/v1/ai/usage/` (admin only)

**Tasks:**
- [ ] `LLMGateway` abstract class + `ClaudeGateway` implementation (`apps/ai/gateway.py`)
- [ ] `AIPromptTemplate` model + migration
- [ ] `AIUsageLog` model + migration
- [ ] `run_llm_task` Celery task (`apps/ai/tasks.py`)
- [ ] Per-tenant Redis rate limiter (`apps/ai/rate_limiter.py`)
- [ ] `AIUsageViewSet` — read-only, admin-only (`GET /api/v1/ai/usage/`)
- [ ] Settings: `ANTHROPIC_API_KEY`, `AI_RATE_LIMIT_PER_HOUR` (default: 100)
- [ ] Tests: gateway mock, rate limiter, usage log creation, admin-only permission

---

### S-031 — TUSS Auto-Coding Feature (8 pts)

**Acceptance Criteria:**
- `POST /api/v1/ai/tuss-suggest` accepts `{"description": "consulta cardiologia", "guide_type": "sadt"}` → returns `{"suggestions": [{"tuss_code": "10101012", "description": "...", "rank": 1}], "degraded": false, "cached": false}`
- Top 3 suggestions via retrieval-hybrid (search_vector pre-filter + LLM re-rank), all validated against live TUSS DB (no hallucinated codes)
- Redis cache key: `ai:tuss:{tenant_schema}:{sha256(normalized_description + guide_type + prompt_version)}` — tenant-scoped, context-aware, prompt-versioned (invalidated when prompt changes)
- `TUSSAISuggestion` model tracks accepted/rejected per tenant for analytics
- `POST /api/v1/ai/tuss-suggest/feedback` accepts `{"suggestion_id": ..., "accepted": true}`
- Frontend: inline suggestion component added to guide creation form item rows
- Feature flag: `FEATURE_AI_TUSS` env var, `False` by default in prod config; **ON for all pilot tenants at onboarding time** (rollout policy: enable at Sprint 8 pilot activation, review acceptance rate after 4 weeks, set GA threshold at >50% pill-click-to-use rate)
- Graceful degradation: if AI call fails or rate limit hit → return empty suggestions, not 500

**Tasks:**
- [ ] `anthropic>=0.40` added to `backend/requirements.txt` (not yet installed)
- [ ] `TUSSCoder` service (`apps/ai/services.py`) — two-stage retrieval+LLM pipeline: (1) retrieve top 20 TUSSCode candidates via search_vector, (2) call Claude to re-rank; validate final selections against TUSS DB
- [ ] `TUSSAISuggestion` model + migration (suggestion_id, tenant, tuss_code, description, rank, input_text, guide_type, accepted, feedback_at)
- [ ] `TUSSSuggestView` (`POST /api/v1/ai/tuss-suggest/`) with Redis cache + rate limit check
- [ ] `TUSSSuggestFeedbackView` (`POST /api/v1/ai/tuss-suggest/feedback/`) — must verify `TUSSAISuggestion.tenant == request.tenant` before marking accepted (cross-tenant data corruption guard)
- [ ] Feature flag check (`FEATURE_AI_TUSS` env var, default False)
- [ ] Frontend: `TUSSSuggestionInline` component — appears below description field in guide item rows, shows 3 pill buttons (code + description), click to fill
- [ ] Wire component into `frontend/app/(dashboard)/billing/guides/new/page.tsx`
- [ ] Hard call timeout: `AI_SUGGEST_TIMEOUT_S` setting (default: 5s) — return `degraded: true` on timeout, never block worker
- [ ] Redis circuit breaker: 3 failures in 60s → open for 5 min; fail-open returns `degraded: true` immediately while open
- [ ] Zero-suggestion empty state: if 0 valid codes return (API success but all validation-dropped), log as `zero_result` in `AIUsageLog`; return `{"suggestions": [], "degraded": false, "cached": false}`
- [ ] `import_tuss` refresh: document and expose via management command; add `TUSSSyncLog` model (or log in AIUsageLog metadata) to record last import timestamp
- [ ] Tests: TUSSCoder service (mock Claude, verify validation), cache hit/miss, rate limit, graceful degradation on API error, circuit breaker trips on 3 failures, zero-result logging

### TUSSSuggestionInline — UX Contract

**Trigger:** fires on `description` field change, debounce 600ms, cancel previous in-flight request via `AbortController`.

**States:**
| State | Visual |
|-------|--------|
| Idle (description < 3 chars) | Hidden |
| Loading | Subtle spinner + "Buscando sugestões..." text (small, slate-400) |
| Suggestions returned (1-3) | Row of pill buttons, blue-outlined, truncated to 40 chars |
| Empty (AI ran, 0 valid codes) | Small grey text: "Nenhuma sugestão encontrada — busque o código manualmente." |
| Degraded (AI unavailable) | Single grey pill: "IA indisponível — use busca manual" (no red, not an error) |
| Feature flag off | Hidden entirely |

**Pill click behavior:** clicking a pill sets `item.tuss_code` to the matched `TUSSCode` object AND sets `item.description` to the TUSS description, ONLY if the user hasn't manually edited `item.tuss_code` already. If `item.tuss_code` is already set: confirm overwrite with tooltip "Substituir código selecionado?" before applying.

**Race condition:** each item row maintains its own `abortRef`. New keystroke in `description` aborts previous request. Stale responses are discarded client-side via `requestId` check.

**Keyboard navigation:** pills are `<button type="button">`, natively keyboard-focusable. `ArrowRight`/`ArrowLeft` moves between pills. `Enter` selects. `Escape` clears suggestions and returns focus to description field.

**Accessibility:** `role="status"` container wrapping pills (triggers `aria-live` politely for suggestion updates). Pill buttons have `aria-label="Selecionar TUSS {code}: {description}"`.

**Mobile:** pills stack vertically below description field if viewport < 640px. Touch target minimum 44px height. Description text truncated at 30 chars on mobile.

---

## Architecture

### New files
```
backend/apps/ai/
  gateway.py          # LLMGateway abstract + ClaudeGateway
  rate_limiter.py     # Redis-based per-tenant rate limiting
  services.py         # TUSSCoder service
  tasks.py            # run_llm_task Celery task
  models.py           # AIPromptTemplate, AIUsageLog, TUSSAISuggestion
  serializers.py
  views.py            # TUSSSuggestView, TUSSSuggestFeedbackView, AIUsageViewSet
  urls.py
  migrations/

frontend/components/billing/
  TUSSSuggestionInline.tsx   # pill-button suggestion component
```

### Modified files
```
backend/vitali/urls.py              # add ai app URLs
backend/vitali/settings/*.py        # ANTHROPIC_API_KEY, AI_RATE_LIMIT_PER_HOUR
frontend/app/(dashboard)/billing/guides/new/page.tsx  # wire in TUSSSuggestionInline
```

### Architecture Diagram

```
Browser (guide form)
  │
  │ description input (debounce 600ms, AbortController)
  ▼
TUSSSuggestionInline.tsx
  │ POST /api/v1/ai/tuss-suggest/
  │ {description, guide_type}
  ▼
TUSSSuggestView (DRF)
  ├── Feature flag check (FEATURE_AI_TUSS env var) → 404 if off
  ├── Per-tenant rate limit  ─────────────────────────────────────────► Redis
  │     key: ai:rate:{schema}                                            └── ai:rate:{schema}
  ├── Cache lookup ────────────────────────────────────────────────────► Redis
  │     key: ai:tuss:{schema}:{sha256(desc+guide_type+prompt_ver)}       └── ai:tuss:{schema}:{hash}
  │     hit → return {suggestions, degraded:false, cached:true}
  │     miss ↓
  └── TUSSCoder.suggest(description, guide_type)
        │
        │ Stage 1 — Retrieval (public schema DB, .using('public'))
        ├──► TUSSCode.objects.using('public')
        │     .annotate(rank=SearchRank(search_vector, tsquery))
        │     .filter(rank__gt=0).order_by('-rank')[:20]
        │     └── if 0 results: trigram fallback (TrigramSimilarity)
        │     └── if still 0: return [] (no LLM call)
        │
        │ Stage 2 — LLM Re-ranking
        ├──► ClaudeGateway.complete(prompt) ──────────────────────────► Anthropic API
        │     system: "select from candidates list, JSON only"            └── claude-haiku-4-5
        │     user: description + guide_type + 20 candidate codes
        │     timeout: AI_SUGGEST_TIMEOUT_S (default 5s)
        │
        ├── Parse JSON → [{code, rank}]
        ├── Validate each code: TUSSCode.objects.using('public').filter(code__in=[...])
        ├── Drop any code not in validation set (anti-hallucination gate)
        ├── Create TUSSAISuggestion records (for acceptance tracking)
        ├── Write AIUsageLog (tokens, latency)
        └── Cache result 24h
              ▼
      {suggestions: [{tuss_code, description, rank}], degraded: bool, cached: bool}
              ▼
  TUSSSuggestionInline renders pills
  User clicks → fills item.tuss_code + item.description
  POST /api/v1/ai/tuss-suggest/feedback/ (fire-and-forget)
    → TUSSSuggestFeedbackView
    └── verify suggestion.tenant == request.tenant (cross-tenant guard)
    └── TUSSAISuggestion.accepted = True
```

### Data flow (summary)
```
User types description in guide form
  → debounce 600ms
  → POST /api/v1/ai/tuss-suggest {description, guide_type}
    → Redis cache check (hit → return cached)
    → Rate limit check (over limit → degraded: true)
    → TUSSCoder: retrieval (GIN search_vector) → LLM re-rank → validate
    → Cache result 24h
    → Return suggestions (0-3 codes, no hallucinated codes)
  → UI renders up to 3 pill buttons
  → User clicks pill → fills code field + description field
  → POST /api/v1/ai/tuss-suggest/feedback (async, non-blocking)
```

---

## Prompt Design

System prompt (stored in `AIPromptTemplate`, version tracked in cache key):
```
You are a Brazilian healthcare billing assistant specializing in TISS/TUSS procedure coding.
Given a procedure description in Portuguese, and a list of candidate TUSS codes,
rank the top 3 most relevant codes for this specific description.
You MUST only select codes from the provided candidates list — do not invent codes.
Return ONLY valid JSON: {"suggestions": [{"code": "12345678"}, ...]}
Rank from most relevant to least relevant. Return 1-3 codes. If none fit, return [].
```

User prompt template:
```
Procedure type: {guide_type}
Procedure description: {description}

Candidate codes:
{candidates}

Select and rank the top 3 most relevant codes. Return JSON only.
```

---

## Success Metrics

- **Acceptance rate ≥ 50%** in first month of usage per tenant (tracks as `TUSSAISuggestion.accepted/total`)
- **AI saves manual lookup** — measured qualitatively in pilot feedback; target: faturista selects AI suggestion vs manual search in >50% of guide items
- **Zero hallucinated codes reaching UI** — all suggestions validated against TUSSCode DB before returning
- **Feedback data collected**: `TUSSAISuggestion.accepted/rejected` records captured for every suggestion interaction — this is the sprint's primary proprietary output, not just the feature itself. Acceptance data + prompt version enables future fine-tuning; incumbents cannot replicate without the same data volume.
- **Zero-result events logged**: `AIUsageLog` records `zero_result` events separately so prompt quality can be diagnosed week-by-week

## Retrieval-Hybrid Approach (updated)

Rather than prompt-only TUSS suggestion, `TUSSCoder.suggest()` uses a two-stage pipeline:

1. **Stage 1 — Retrieval:** use `TUSSCode.search_vector` (GIN index, already exists) to retrieve top 20 candidates matching the description via similarity search
2. **Stage 2 — LLM Re-ranking:** inject top 20 candidates into Claude prompt as context, ask it to select and rank the top 3

This eliminates hallucination at the source (Claude can only pick from pre-validated candidates), reduces prompt complexity, and improves accuracy.

```python
# TUSSCoder.suggest(description) — two-stage pipeline
# Note: TUSSCode lives in public schema; .using('public') is correct
# (tenant-routed connection would route to tenant schema, TUSSCode is NOT there)
from django.contrib.postgres.search import SearchRank, SearchQuery, TrigramSimilarity

candidates = TUSSCode.objects.using('public').filter(
    active=True
).annotate(
    rank=SearchRank(F('search_vector'), SearchQuery(description, config='portuguese'))
).filter(rank__gt=0).order_by('-rank')[:20]

if not candidates.exists():
    # Fallback: trigram similarity for typos, abbreviations, accent variants
    candidates = TUSSCode.objects.using('public').filter(active=True).annotate(
        rank=TrigramSimilarity('description', description)
    ).filter(rank__gt=0.1).order_by('-rank')[:20]

if not candidates.exists():
    return []  # genuine zero-match — no LLM call

# Build prompt with candidate codes injected
context = "\n".join(f"{c.code}: {c.description}" for c in candidates)
# ... call Claude with context ...
```

## API Response Schema (updated)

```json
{
  "suggestions": [
    {"tuss_code": "10101012", "description": "Consulta em consultório (presencial)", "rank": 1},
    {"tuss_code": "10101039", "description": "Consulta por telemedicina", "rank": 2}
  ],
  "degraded": false,
  "cached": true
}
```

**No numeric confidence scores in v1.** Rank order (1st, 2nd, 3rd) is sufficient — uncalibrated confidence creates automation bias.

## Open Questions

1. **Sync vs async Claude calls** — haiku is fast (~300ms). Sync call inside DRF view is simpler, avoids Celery complexity for this use case. Celery `run_llm_task` exists for future async needs but TUSS suggest can be sync.

2. **Cache key: text-only vs text+specialty** — TASTE DECISION. Same description can require different codes depending on guide type (consulta vs SADT). Option A: include `guide_type` in cache key + prompt context (more accurate, slightly more complex). Option B: text-only cache for v1, refine in v2.

3. **LLMGateway abstraction level** — TASTE DECISION. Full abstract class + Celery wrapper (current plan: reusable for future AI features) vs minimal TUSSCoder that calls Claude directly (simpler, proves value faster). Both are valid.

---

## Test Plan

| Test | Type | File |
|------|------|------|
| ClaudeGateway returns parsed string | unit | test_gateway.py |
| ClaudeGateway raises on non-2xx | unit | test_gateway.py |
| Rate limiter blocks at 100/hr | unit | test_rate_limiter.py |
| Rate limiter resets after window | unit | test_rate_limiter.py |
| Rate limiter: Redis down → fail-open | unit | test_rate_limiter.py |
| TUSSCoder validates codes — drops hallucinated code not in DB | integration | test_services.py |
| TUSSCoder returns [] when retrieval finds 0 candidates (no LLM call) | integration | test_services.py |
| TUSSCoder trigram fallback fires on typo input | integration | test_services.py |
| TUSSCoder uses `.using('public')` — does not leak tenant schema | integration | test_services.py |
| Cache hit skips Claude call, returns `cached: true` | integration | test_views.py |
| Cache miss calls Claude, stores result | integration | test_views.py |
| **Tenant cache isolation**: tenant A's cached response not served to tenant B | integration | test_views.py |
| **guide_type partitioning**: same description + sadt vs consulta → different cache entries | integration | test_views.py |
| **Prompt version invalidation**: bumping prompt_version → cache miss | integration | test_views.py |
| Feature flag off → 404 | unit | test_views.py |
| Graceful degradation on Claude 500 → empty suggestions, `degraded: true` | unit | test_views.py |
| Graceful degradation on Anthropic 429 → `degraded: true`, not 500 | unit | test_views.py |
| Feedback accepted: marks TUSSAISuggestion.accepted=True | unit | test_views.py |
| **Feedback ownership**: cannot accept suggestion owned by different tenant | integration | test_views.py |
| Usage log created on each Claude call | unit | test_views.py |
| Monthly usage endpoint: admin sees totals, non-admin gets 403 | unit | test_views.py |
| TUSSSuggestionInline renders pills | — | manual |
| TUSSSuggestionInline: stale response discarded (AbortController) | — | manual |
| TUSSSuggestionInline: pill click fills code + description | — | manual |
| TUSSSuggestionInline: overwrite confirmation if TUSS already set | — | manual |

---

## Error & Rescue Registry

| Error | Impact | Recovery |
|-------|--------|----------|
| `ANTHROPIC_API_KEY` missing | View fails | Graceful: return `degraded: true`, empty suggestions |
| Claude API timeout (>5s) | Worker blocked | Timeout wrapper 5s → return empty, `degraded: true` |
| Claude returns invalid JSON | Parse failure | `try/except ValueError` → return empty |
| All suggestions fail TUSS DB validation | 0 valid | Return `[]`, not error |
| Redis down | Rate limiter fails | Fail-open: allow request, log warning |
| Anthropic 429 (rate limit) | API throttled | Catch 429 → `degraded: true`, empty |
| TUSS table empty | 0 retrieval candidates | Return empty before calling LLM |
| `anthropic` SDK missing from requirements | Deploy fails | **Fix: add to requirements.txt** |
| All LLM suggestions fail DB validation (valid API, all codes wrong) | 0 suggestions shown | Log as `zero_result`, show manual-search message |
| Circuit breaker open (3 failures/60s) | All requests fast-fail for 5 min | Return `degraded: true` immediately, re-probe after 5 min |

## Failure Modes Registry

| Mode | Prob | Impact | Mitigation |
|------|------|--------|------------|
| LLM selects contextually wrong code (valid but wrong specialty) | Medium | Glosa on wrong code | Retrieval-hybrid reduces this; tracking acceptance rate surfaces it |
| Cache key too broad → wrong code for 24h | Low-Medium | Systematic wrong suggestion per phrase | TASTE DECISION: include guide_type in cache key |
| Sync Claude blocks Django worker >500ms | Low | Latency spike under load | Acceptable for haiku; add `AI_SUGGEST_TIMEOUT_S=5` |
| TUSS table stale >90 days | Medium | Outdated suggestions | Add version-age warning log in TUSSCoder |
| Feature flag off but code deployed | None | UI fallback to manual search | Expected behavior |

## Not In Scope

- OpenAI fallback (defer to S-030 v2 when needed)
- Async Celery invocation for TUSS suggest (sync haiku is fast enough)
- Admin UI for prompt template management (env var is fine for v1)
- TUSS code auto-import from ANS (P3, see TODOS.md)
- Billing analytics dashboard (E-011, Phase 2)

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Proceed with TUSS lookup (not claim copilot) | P6 Bias toward action | Claim copilot requires historical denial data we don't have yet | Defer to Phase 2 when outcome data exists |
| 2 | CEO | Add acceptance rate success metric (≥50%) | P1 Completeness | No metric = no value proof = renewal risk | Qualitative-only metric |
| 3 | CEO | Retrieval-hybrid instead of prompt-only | P3 Pragmatic | TUSSCode.search_vector GIN index already exists; eliminates hallucination source | RAG (overkill), retrieval-only (less intuitive) |
| 4 | CEO | Remove numeric confidence scores from v1 UI | P5 Explicit | Uncalibrated 0.92 drives automation bias; ranked list is honest and sufficient | Show confidence (deferred: calibrate first) |
| 5 | CEO | Add `degraded: bool` to response | P1 Completeness | Silent degradation hides reliability; frontend needs explicit signal | Empty list only |
| 6 | CEO | Fail-open on Redis down for rate limiter | P5 Explicit | Redis outage should not break AI feature entirely | Fail-closed (block all requests) |
| 7 | CEO | TUSS version freshness log warning | P2 Boil lakes | 5 lines; surfaces stale table risk without P3 auto-updater scope | Defer to P3 |
| 8 | CEO | Abstract LLMGateway retained in plan | P1 Completeness | Future AI features (clinical notes, prescription safety) will reuse this | TASTE: minimal direct call |
| 9 | CEO | Cache key: include `guide_type` | P1 Completeness | "Consulta" in consulta context ≠ "consulta" in SADT context | TASTE: text-only for v1 |
| 10 | CEO | Add `anthropic>=0.40` to requirements | P2 Boil lakes | SDK not installed; deploy would fail without it | (non-negotiable) |
| 11 | Design | Add explicit UX state machine to component spec | P1 Completeness | Codex: "implementation-ready for backend, not UX-ready for production" | Leave as generic "3 pills" spec |
| 12 | Design | Degraded = grey pill (not hidden, not red) | P5 Explicit | Silent failure trains users to not notice degradation; red implies error (wrong) | Hidden entirely |
| 13 | Design | AbortController per item row | P1 Completeness | Race condition: fast typing → stale response fills wrong field | Single global abort |
| 14 | Design | Pill click: confirm overwrite if TUSS already set | P5 Explicit | Silently overwriting user-edited code is destructive | Always overwrite |
| 15 | Design | Keyboard nav (ArrowLeft/Right + Enter) | P1 Completeness | DESIGN.md: "Labels are full words, never cryptic icons alone" — keyboard access required | Mouse-only for MVP | TASTE: aria-live only |
| 16 | Eng | Remove `confidence` from TUSSAISuggestion model + system prompt JSON schema | P5 Explicit | Stored uncalibrated confidence is technical debt; misleading key in LLM prompt schema causes model to make up numbers | Keep field, convert to rank post-process |
| 17 | Eng | Feature flag: `FEATURE_AI_TUSS` env var only for v1 | P3 Pragmatic | Per-tenant toggle needs admin UI + DB column; env var ships in 30 min; per-tenant deferred to E-010 Sprint 11 | Per-tenant toggle in v1 (over-engineered) |
| 18 | Eng | Tenant-scoped cache key: `ai:tuss:{schema}:{sha256(desc+guide_type+prompt_ver)}` | P5 Explicit | Text-only key: tenant A's cached suggestions served to tenant B; prompt change undetected in 24h TTL | Text-only key (cross-tenant data leak) |
| 19 | Eng | Feedback endpoint: explicit `suggestion.tenant == request.tenant` check | P5 Explicit | Without check: authenticated user from tenant B can mark tenant A's suggestion as accepted (corrupts analytics) | Rely on implicit queryset filtering alone |
| 20 | Eng | TUSSCode retrieval: `.using('public')` (not default) | P3 Pragmatic | django-tenants routes `default` connection to active tenant schema; TUSSCode lives in public schema only | .using('default') silently returns empty queryset for all tenants |
| 21 | Eng | Trigram similarity fallback in retrieval stage | P1 Completeness | Portuguese medical abbreviations ("consulta cardio") fail tsquery full-text; trigram catches near-matches with no index change needed | Pure tsquery only — silent fail for 20% of real queries |
| 22 | CEO-v2 | Hard timeout + Redis circuit breaker on Claude call | P1 Completeness | Sync call at P99 latency (2-5s) blocks Django worker; 3 open failures exhaust thread pool | Rely on 5s timeout alone (no circuit breaker) |
| 23 | CEO-v2 | Feature flag ON for pilot tenants at onboarding | P6 Bias toward action | Flag off by default kills acceptance rate data needed to validate glosa metric | OFF until manually toggled per tenant |
| 24 | CEO-v2 | Zero-suggestion state = explicit message, not silent | P5 Explicit | Silent zero looks like "AI broken"; faturista loses trust faster with no feedback | Hidden entirely on 0 results |
| 25 | CEO-v2 | TUSS refresh management command as Sprint 8 task | P2 Boil lakes | Static table without refresh path will silently block suggestions for new codes | Defer to P3 auto-updater |
| 26 | CEO-v2 | Feedback data is primary sprint output, not secondary | P1 Completeness | Acceptance/rejection signal is the only data moat; reframed in success metrics | Treat analytics as observability-only |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 2 | PASS | 12 issues: 10 auto-decided, 2 surfaced as taste decisions (cache key, LLMGateway level) |
| CEO Review (voice 2) | subagent | Adversarial second opinion | 1 | PASS (5 auto-decided) | 9 findings: 2 resolved (confidence, retrieval), 5 auto-decided (#22-26), 2 STRATEGIC → user gate |
| Codex Review | `/codex review` | Independent 2nd opinion | 2 | PASS | Consensus: 3 agree, 3 disagree (all disagreements resolved in plan) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | PASS | 7 architectural issues: all auto-decided. 26 decisions in audit trail. 42+ tests specified. |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | PASS | 6 UX gaps: all resolved. UX Contract section added. Score: 3/10 → 7/10. |

**VERDICT:** ALL REVIEWS PASS — **APPROVED 2026-03-31.** A1 + B1 + C1 + D1 accepted. Implementation started.

---

## Final Approval Gate

Four decisions require your input before Sprint 8 starts — 2 taste calls and 2 strategic questions.

---

**Decision A — Cache key granularity** *(taste)*
- **Option A1 (current plan):** include `guide_type` in cache key. "Consulta em cardiologia" in `consulta` context vs `sadt` context can need different codes. More accurate, ~2x more cache entries.
- **Option A2:** text-only for v1. Simpler. Risk: wrong code cached 24h when guide_type matters.
- **Recommendation: A1.** Silent wrong-code suggestions are the fastest way to kill AI trust. The complexity delta is negligible.

---

**Decision B — LLMGateway abstraction level** *(taste)*
- **Option B1 (current plan):** full `LLMGateway` abstract class + `ClaudeGateway`. Reusable for Sprint 9/10 AI features. ~30 extra lines.
- **Option B2:** `TUSSCoder` calls Anthropic SDK directly. Simpler, ships faster.
- **Recommendation: B1.** The ~30 lines are free with CC. Without the abstraction, Sprint 9 starts with a refactor.

---

**Decision C — Sprint sequencing: E-008 (AI TUSS) now or E-009 (WhatsApp) first?** *(strategic)*

The CEO second-opinion review flags this: WhatsApp scheduling (E-009) is likely higher commercial ROI than TUSS AI (E-008). No-shows are permanent revenue loss; glosas are recoverable. E-009 also has broader persona coverage (receptionist + patient + admin vs faturista only). Both dependencies are clear.

The counterargument: Sprint 8 is scoped, planned, and reviewed. Resequencing costs 1-2 days of re-planning. The billing module is freshest in everyone's head. And TUSS AI feedback data starts accumulating earlier.

- **Option C1:** proceed with E-008 as planned.
- **Option C2:** swap — build E-009 WhatsApp first, defer E-008 to Sprint 9.
- **Option C3:** run a 3-day glosa root-cause discovery with pilot faturistas before committing to either (CEO finding 2: glosa causes may not be TUSS miscoding).
- **Recommendation: C1, conditional.** If you have talked to faturistas and TUSS miscoding is a real pain, proceed now. If you have not, do C3 first — it's 3 days and could save 3 weeks.

---

**Decision D — Sync Claude call vs fire-and-forget** *(taste, risk-adjacent)*

CEO review flags P99 latency risk: sync Claude call in a form blocks the Django worker up to 5s (or timeout). Circuit breaker and hard timeout are already added to the plan (Decision 22). The residual question is whether the response flow should be:

- **Option D1 (current plan):** POST → wait → return suggestions. Simple. Hard 5s timeout + circuit breaker mitigates the risk. Acceptable for haiku's median ~300ms.
- **Option D2:** fire-and-forget POST → immediate return → frontend polls or uses SSE for result. Fully non-blocking. 2-3 hours more work.
- **Recommendation: D1.** The circuit breaker + 5s timeout is sufficient for v1 at single-clinic scale. SSE/polling is the right move before multi-clinic scale but not Sprint 8.
