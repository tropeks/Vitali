# Vitali — AI Agent Development Rules

> Project-specific rules for AI agents (Claude Code, Codex, etc.) executing tasks on this codebase. Not a developer onboarding doc. Not general knowledge.

## Project Overview

- **What:** Vitali is a Brazilian SaaS healthtech platform. ERP + EMR + AI for small/medium private clinics.
- **Stack:** Django 5 (backend) + Next.js 14 App Router (frontend) + PostgreSQL + Redis + Celery + Anthropic Claude.
- **Multi-tenancy:** `django-tenants` with schema-per-tenant. Public schema for shared models (Tenant, Subscription, FeatureFlag, TUSSCode, CID10Code). Tenant schemas for clinical data.
- **Compliance:** LGPD (Brazilian GDPR) + CFM Res. 1.821/2007 (electronic medical records). Both regulations matter; they sometimes conflict.

## Project Architecture

### Backend (`backend/`)

- All Django apps live under `backend/apps/`. Use **English short names**: `apps.core`, `apps.emr`, `apps.billing`, `apps.pharmacy`, `apps.ai`, `apps.whatsapp`, `apps.analytics`, `apps.hr` (new in Sprint 18). **Never** use Portuguese names like `apps.recursos_humanos`.
- Module activation gated by `apps/core/constants.py:ALLOWED_MODULE_KEYS`. New module → must add to this set.
- Settings split across `backend/vitali/settings/{base,development,production,staging}.py`.
- Migrations live in each app's `migrations/`. Always reversible. Always safe under concurrent writes (use `RunPython.noop` for reverse, no destructive default values).

### Frontend (`frontend/`)

- Next.js 14 App Router. Routes under `frontend/app/`.
- **Routing convention is PT-BR for tenant-facing pages**: `/configuracoes/*`, `/farmacia/*`, `/rh/*`, `/auth/*`. Internal/technical routes stay English: `/dashboard`, `/billing`, `/encounters`, `/patients`, `/appointments`. Match existing routes when adding new ones — do NOT mix conventions inside the same module.
- Dashboard nav defined in `frontend/components/layout/DashboardShell.tsx`. Adding a new page → add nav entry there with `module:` (gates by FeatureFlag) or `adminOnly: true`.
- `getAccessToken()` from `frontend/lib/auth.ts` for JWT in all `fetch()` calls. Never read tokens from localStorage directly.

### Documentation

- `docs/EPICS_AND_ROADMAP.md` — canonical epic + sprint plan. Every new module/epic must add an `E-NNN` entry here.
- `docs/PLAN_SPRINT*.md` — historical sprint plans. New sprints get a new file.
- `docs/PROJECT_BRIEF.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `API_SPEC.md` — design references.
- `CHANGELOG.md` — release history. Update on every version cut.
- `TODOS.md` — open work backlog. Append items with the standard format (What/Why/Pros/Cons/Context).

## Code Standards

### Backend (Python/Django)

- Linting: `ruff check` + `ruff format`. CI gate.
- Type checking: `mypy apps/ vitali/ --ignore-missing-imports`. CI gate.
- Test runner: `pytest -v` (via `make test` which runs inside `docker compose exec django`).
- All three available baked into the dev image when `INSTALL_DEV=true` (set automatically by `docker-compose.override.yml`).
- Use `transaction.atomic()` around any multi-step DB writes. Use `transaction.on_commit(lambda: task.delay(...))` to enqueue Celery tasks AFTER commit — NEVER call `.delay()` directly inside a transaction, the task may run before commit and read stale data.
- AuditLog (`apps.core.models.AuditLog`) is append-only. Never UPDATE or DELETE rows. For cascade chains, use `correlation_id: uuid4()` in `new_data` JSON to group sibling entries.
- Soft-delete is the default: `is_active=False`. Hard-delete (`DELETE FROM`) only via explicit user action with confirmation modal — required for LGPD right-of-erasure but breaks CFM medical record attribution. Default to soft.

### Frontend (TypeScript/React)

- Linting: `next lint`. CI gate.
- Type checking: `tsc --noEmit`. CI gate.
- Hook deps: `react-hooks/exhaustive-deps` is treated as error. Use `useCallback` + `useRef<setTimeout>` pattern for debouncers, not a home-rolled `debounce(fn, ms)` wrapper (the wrapper defeats deps tracking).
- Visual conventions per `DESIGN.md`: slate borders (`border-slate-200`), rounded-xl cards, blue primary buttons (`bg-blue-600 hover:bg-blue-700`), lucide-react icons, max-w-2xl-or-3xl content widths.
- All forms: plain `useState`. Do not introduce `react-hook-form` or `formik` unless explicitly approved — existing code is consistent with `useState`.

### Naming

- Models: PascalCase (`Employee`, `PrescriptionItem`).
- Functions/methods: snake_case (`onboard_employee`, `notify_next_waitlist_entry`).
- React components: PascalCase (`PIXModal`, `DPASignModal`).
- Files: snake_case Python, PascalCase or kebab-case React.
- Migrations: numbered + descriptive (`0013_appointment_arrived_started.py`).

## Functionality Implementation Standards

### Cascade pattern (E-013 Workflow Intelligence)

When implementing a state-change cascade (HR onboarding, appointment-created, encounter-signed, etc.):

- **Pattern:** explicit service-layer orchestrator. New file `apps/{module}/services.py:{Resource}{Action}Service.{action}(payload, *, requesting_user)`. View calls service directly. **Do NOT use Django `post_save` signals** for cascades with ordering requirements (User must exist before Professional FK can resolve).
- **Transaction shape:** all DB writes in single `transaction.atomic()`. External-system calls (WhatsApp, Email) enqueued via `transaction.on_commit(lambda: task.delay(...))` AFTER commit. Fail-open: external failure does NOT roll back DB.
- **Audit:** one AuditLog entry per resource side-effect, all sharing `correlation_id` in `new_data` JSON.
- **Tests:** unit test the orchestrator with mocked Celery + integration test with real Celery worker for fail-open behavior. Both required.
- **Reference implementation:** `apps/emr/tasks_waitlist.py:notify_next_waitlist_entry` (existing) and the upcoming `apps/hr/services.py:EmployeeOnboardingService` (Sprint 18).

### Adding a new Django app

1. `python manage.py startapp {name} backend/apps/{name}` (or create manually).
2. Add to `backend/vitali/settings/base.py:TENANT_APPS` (if tenant-scoped) or `SHARED_APPS` (if cross-tenant).
3. If module is feature-gated, add key to `backend/apps/core/constants.py:ALLOWED_MODULE_KEYS`.
4. Add admin registration in `apps/{name}/admin.py`.
5. Add URL include in `backend/vitali/urls.py`.

### Adding a new frontend page

1. Create `frontend/app/{route}/page.tsx`. Match PT-BR convention if user-facing tenant page.
2. Add nav entry in `frontend/components/layout/DashboardShell.tsx:NAV_ITEMS` with `module:` (FeatureFlag gate) and/or `adminOnly: true` if admin-only.
3. Use `getAccessToken()` for JWT, `'use client'` directive at top, `lucide-react` for icons.
4. Match visual conventions (slate, blue, rounded-xl).
5. **Verify the route resolves** — broken nav entries (page.tsx missing) ship 404s.

### Adding a feature flag

- Tenant-level: add module key to `ALLOWED_MODULE_KEYS`, FeatureFlag rows are auto-created/synced via `apps.core.signals.py` on Tenant/Subscription save.
- Per-user permission: add string to `Role.permissions` JSON array. Reference in DRF `permission_classes` via `HasPermission("module.action")`.

## Framework/Plugin/Third-party Library Usage Standards

### Django patterns

- `OneToOneField` with `related_name`: always required for reverse access.
- `EncryptedCharField` / `EncryptedTextField` from `encrypted_model_fields` for PII (CPF, raw_transcription, etc.). Requires `FIELD_ENCRYPTION_KEY` env var (Fernet 32-byte key).
- `ModuleRequiredPermission("module")` from `apps.core.permissions` is an INSTANCE in `permission_classes`, not a class. Stubs reject this — use `# type: ignore[list-item]` annotation.
- Celery tasks: `@shared_task(bind=True, max_retries=N, default_retry_delay=N)`. Always idempotent (re-run safe).

### Anthropic SDK

- All Claude calls go through `apps.ai.gateway.ClaudeGateway`. Never instantiate `anthropic.Anthropic()` directly elsewhere.
- Content blocks are a 12-way union — never assume `message.content[0].text` exists. Use `getattr(first, "text", "") or ""`.
- Feature flags `FEATURE_AI_*` gate all AI features. Default OFF.
- DPA must be signed (`AIDPAStatus.is_signed`) before any AI feature can run.

### rest_framework_simplejwt

- Use `RefreshToken(token).blacklist()` to revoke individual tokens. For user-wide revoke (e.g., F-15 deactivation), iterate `OutstandingToken.objects.filter(user=user)`.
- New JWT claims: add to `apps.core.serializers.HealthOSTokenObtainPairSerializer.get_token()`.

## Workflow Standards

### Sprint flow (gstack methodology)

```
   Office hours / CEO review     /plan-eng-review     /plan-design-review (if UI)
   ────────────────────────►     ────────────────►   ──────────────────────►
   Design doc in ~/.gstack/      Lock architecture    Lock visual design
                                    │
                                    ▼
                            Shrimp plan_task → execute_task (continuous mode)
                                    │
                                    ▼
                            /review → /qa → /ship → /land-and-deploy
```

- Sprint plans live in `docs/PLAN_SPRINT{N}.md`.
- Design docs live in `~/.gstack/projects/tropeks-Vitali/`.
- Test plans (from /plan-eng-review) live alongside design docs in `~/.gstack/projects/tropeks-Vitali/`.
- Each sprint = one feature theme. Do not mix unrelated stories across sprints.

### CI / Deploy

- Branch naming: `{type}/{description}` where type ∈ {feat, fix, chore, docs, ci}. Examples: `feat/hr-onboarding-cascade`, `fix/audit-log-correlation-id`.
- PRs: use the `.github/pull_request_template.md`. Squash and merge.
- CI jobs: `backend-lint`, `backend-test`, `frontend-lint`, `docker-validate`. All must pass before merge.
- Production deploy: Fly.io via GitHub Actions. Staging gated by `STAGING_ENABLED` repo var.

## Key File Interaction Standards

- Modify `backend/apps/core/constants.py:ALLOWED_MODULE_KEYS` → also update `docs/EPICS_AND_ROADMAP.md` epic table → also potentially update `docs/PROJECT_BRIEF.md` if positioning changes.
- Modify `frontend/components/layout/DashboardShell.tsx:NAV_ITEMS` → ensure every new `href` resolves to an existing `page.tsx` (broken nav → 404 in production).
- Modify `User` model → migration must be reversible AND safe under concurrent writes (no NOT NULL columns without default).
- Modify any model with an FK to `User` → consider deactivation cascade behavior (CFM requires permanent attribution; LGPD requires erasability).
- Modify `apps/core/middleware.py` → add to `MIDDLEWARE` list in `vitali/settings/base.py` in correct order (auth-related middlewares come BEFORE module/feature gates).
- Modify any `tasks.py` → ensure tasks are idempotent (Celery may retry).

## AI Decision-Making Standards

### Cascade vs CRUD: when does a state change need a cascade?

If you're adding a model with a `save()` that other modules CARE about (e.g., new Employee creates a User; new Appointment notifies a patient), use the cascade pattern. If it's a leaf entity nobody listens to (e.g., a personal note), plain CRUD is enough.

### Soft vs hard delete: which one?

- Default: **soft delete** (`is_active=False` or `status=terminated`). Preserves CFM attribution.
- Hard delete only via explicit user action with confirmation modal (LGPD right-of-erasure). Must check that the user has no active medical record signatures OR retention period has passed.
- Never hard-delete by default for any entity that touches medical records (User, Professional, Patient, Encounter, Prescription).

### Permission gate: where does it go?

- Backend: DRF `permission_classes`. Always include `IsAuthenticated`. Add `HasPermission("module.action")` or `ModuleRequiredPermission("module")` for fine-grained.
- Frontend: nav-level via `adminOnly: true` or `module:` in NAV_ITEMS. Component-level via `useHasPermission("module.action")` hook (if exists; otherwise add).
- **Both.** Backend is the source of truth — frontend gates are UX hints, not security.

### Test type: unit, integration, or E2E?

- Pure logic, single function: **unit**.
- Cross-module workflow (cascade, signal, Celery task): **integration** with real worker.
- User-facing critical flow (login, hire-a-doctor, sign-an-encounter): **E2E** (Playwright/Cypress).
- LLM/prompt change: **eval suite** (output quality, not just code path).

## Prohibited Actions

- ❌ **Do NOT use Django `post_save` signals for cascades with ordering requirements** (User → Professional → WhatsApp). Use service-layer orchestrator instead.
- ❌ **Do NOT call `.delay()` on Celery tasks inside an open transaction.** Always wrap in `transaction.on_commit(lambda: task.delay(...))`.
- ❌ **Do NOT add UI navigation entries that point to nonexistent routes.** This produces 404s in production. Verify the `page.tsx` exists before adding to `NAV_ITEMS`.
- ❌ **Do NOT mix English and PT-BR routing conventions inside the same module.** Pick one and match existing routes.
- ❌ **Do NOT hard-delete data by default.** Soft-delete is the rule. Hard-delete is opt-in via confirmation modal.
- ❌ **Do NOT bypass `ClaudeGateway`** for AI calls. All Anthropic API calls go through it.
- ❌ **Do NOT introduce new state management libraries** (Redux, Zustand, Jotai, etc.). Existing code is plain `useState` — match it.
- ❌ **Do NOT introduce new form libraries** (`react-hook-form`, `formik`). Plain `useState` is the convention.
- ❌ **Do NOT skip `INSTALL_DEV=true` arg when rebuilding the django image** during dev. The override.yml passes it; if you build manually, you'll lose pytest/ruff/mypy in the container.
- ❌ **Do NOT commit `.env` files.** Always gitignored. Use `.env.example` as the template.
- ❌ **Do NOT install npm packages globally** in the dev container — pin via `frontend/package.json`.
- ❌ **Do NOT use Portuguese in Python module names** (`apps.recursos_humanos` ❌ → `apps.hr` ✅).
- ❌ **Do NOT use English in user-facing tenant routes when convention is PT-BR** (`/settings/ai` ❌ → `/configuracoes/ai` ✅).
- ❌ **Do NOT skip AuditLog entries for cascade side-effects.** CFM Res. 1.821 + LGPD Art. 37 require per-resource attribution. Always write one entry per resource with shared `correlation_id`.

## What can be done — concrete examples

✅ Adding a new feature flag for `ai_radiology`:
1. Add `"ai_radiology"` to `ALLOWED_MODULE_KEYS`.
2. Add migration if FeatureFlag rows need backfill for existing tenants.
3. DRF: gate views with `permission_classes = [IsAuthenticated, ModuleRequiredPermission("ai_radiology")]`.
4. Frontend: add `module: "ai_radiology"` to relevant NAV_ITEMS entries.

✅ Adding a state-change cascade (e.g., F-02 appointment confirmation):
1. New file `apps/emr/services/appointment_confirmation.py:AppointmentConfirmationService.confirm(appointment, *, requesting_user)`.
2. Wrap DB updates in `transaction.atomic()`. Enqueue WhatsApp via `transaction.on_commit(lambda: send_appointment_confirmation.delay(appointment.id))`.
3. Write AuditLog with `correlation_id` for the cascade.
4. Service called from `AppointmentViewSet.create()` after `serializer.save()`. View stays thin.
5. Unit test the service with mocked Celery + integration test with real worker for fail-open.

✅ Editing the navigation:
1. Open `frontend/components/layout/DashboardShell.tsx`.
2. Add NEW NavItem with `href`, `icon`, `label`, optional `module:` and/or `adminOnly: true`.
3. **Verify** `frontend/app/{route}/page.tsx` exists. If not, create it BEFORE merging.
