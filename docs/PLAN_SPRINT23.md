# Sprint 23: HR E2E Gate and Role Contract Hardening

## Goal

Turn the HR/invite Playwright suite from a tolerated warning into a blocking product gate, then harden the backend contracts that make the flow reliable in every tenant.

## Root Cause

The failing E2E tests were not flaky modal timing. The product contract was incomplete:

1. CI created the `testclinic` tenant/domain but did not run `create_default_roles --schema testclinic`, so HR onboarding rejected submitted roles.
2. The HR UI and Playwright used `recepcao`, but `DEFAULT_ROLES` only seeded `recepcionista`.
3. The HR UI offered `dentista`, but `DEFAULT_ROLES` did not seed it.
4. Older frontend enum values (`on_leave`, `estagiario`, `autonomo`) did not match the backend model choices (`leave`, `estagio`, `temporary`).
5. The E2E job was allowed to fail with `continue-on-error`, so real product regressions could merge.

## Shipped Scope

### S23-01: Tenant Role Contract

- `recepcao` is now seeded as the canonical reception role.
- `recepcionista` remains as a legacy alias with the same permissions.
- `dentista` is now seeded as a clinical prescriber role.
- Permission lists are named constants so aliases cannot drift silently.

### S23-02: HR Onboarding Compatibility

- The HR onboarding serializer normalizes legacy frontend aliases before DRF `ChoiceField` validation.
- Canonical persisted values remain aligned with `Employee` model choices.
- Regression tests cover invite mode, medico random-password onboarding, dentista onboarding, and enum alias normalization.

### S23-03: CI E2E Bootstrap

- CI now seeds default roles in the `testclinic` tenant before Playwright runs.
- CI creates or refreshes `admin@test.com` with `full_name`, password, superuser flags, and the tenant `admin` role.
- The Playwright E2E job no longer uses `continue-on-error`.

### S23-04: Documentation

- `frontend/e2e/README.md` documents the local and CI bootstrap contract.
- This plan records the root cause, acceptance criteria, and verification path.

## Acceptance Criteria

- Backend regression tests pass.
- Frontend lint/type-check pass.
- Playwright HR/invite specs pass in CI as a blocking gate.
- A tenant seeded with `create_default_roles` can onboard `recepcao`, `medico`, and `dentista` employees.
- Legacy enum payloads continue to work while data is stored canonically.

## Verification Commands

Backend:

```bash
docker compose exec -T django pytest -v apps/core/tests/test_default_roles.py apps/hr/tests/test_api_onboarding.py
```

Frontend:

```bash
cd frontend
npm run lint
npm run type-check
npx playwright test frontend/e2e/hr-onboarding.spec.ts frontend/e2e/invite-flow.spec.ts
```

CI is the source of truth for this sprint because it exercises Docker, tenant routing, role seeding, and Playwright together.

## Non-Goals

- Redesigning the HR employee table.
- Reworking the invite token helper outside E2E safety gates.
- Making mypy blocking; that remains tracked separately.
