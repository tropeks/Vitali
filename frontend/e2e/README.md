# E2E tests

Playwright tests for Vitali HR onboarding flows (Sprint 18, E-013).

## Specs

| File | Description | Status |
|------|-------------|--------|
| `hr-onboarding.spec.ts` | Admin hires a doctor via 3-step modal; verifies row appears in `/rh/funcionarios` table | Runnable end-to-end |
| `invite-flow.spec.ts` | Admin creates employee with invite auth mode; set-password journey is skipped | Admin step runnable; token step skipped (Sprint 19) |

## Run locally

### 1. Start the backend stack

```bash
docker compose up -d
docker compose exec django python manage.py migrate_schemas --shared
```

### 2. Seed a test admin user

```bash
docker compose exec django python manage.py createsuperuser \
  --email admin@test.com \
  --noinput
# Then set the password manually:
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(email='admin@test.com')
u.set_password('AdminPass1!')
u.save()
"
```

### 3. Start the frontend dev server

```bash
cd frontend && npm run dev
```

### 4. Run the E2E tests

```bash
cd frontend && npm run test:e2e
```

Or with the Playwright UI (interactive, shows browser):

```bash
cd frontend && npm run test:e2e:ui
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `E2E_BASE_URL` | `http://localhost:3000` | Frontend URL |
| `E2E_BACKEND_URL` | `http://localhost:8000` | Backend URL (reserved for future use) |
| `E2E_ADMIN_EMAIL` | `admin@test.com` | Pre-seeded admin email |
| `E2E_ADMIN_PASSWORD` | `AdminPass1!` | Pre-seeded admin password |

## Selector strategy

All form inputs inside `AddEmployeeModal` use `id=` attributes matching the
form field names (`#full_name`, `#email`, `#cpf`, `#phone`, `#role`,
`#hire_date`, `#contract_type`, `#council_type`, `#council_number`,
`#council_state`, `#specialty`). Auth-mode radios are selected via
`input[type="radio"][value="<mode>"]`. No `data-testid` attributes were
needed because the existing `id=` coverage is sufficient.

The login form (`/auth/login`) uses `react-hook-form`'s `register()` spread
which renders `name="email"` and `name="password"` on the inputs — selectors
`input[name="email"]` and `input[name="password"]` target these reliably.

## Known gaps (Sprint 19)

### 1. Invite token retrieval

The invite-flow test (`invite-flow.spec.ts`) skips the set-password portion
because Playwright has no way to retrieve the `UserInvitation` JWT that the
backend mints when an employee is created with `auth_mode=invite`.

Proposed solutions for Sprint 19 (pick one):

**a) Management command**

```bash
docker compose exec django python manage.py get_invitation_token <email>
```

Would output the raw JWT. The test can run this via `execSync` in a `test.beforeAll`.

**b) DEBUG-gated REST endpoint**

```
GET /api/v1/auth/invitations/by-email/<email>/token/
```

Only enabled when `DEBUG=True`. Returns `{ "token": "<jwt>" }`.
Playwright can call this via `request.get(...)` before visiting the link.

**c) Email backend mock**

Configure `EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'`
and `EMAIL_FILE_PATH = /tmp/e2e-emails` in the test settings. Parse the token
from the saved `.eml` file after employee creation.

### 2. Database isolation

Tests use timestamped emails (`dr.teste+<timestamp>@vitali.com`) to avoid
collisions between runs. Full DB reset between tests is not implemented.
Sprint 19 should add a fixture that resets the `employees` and `users` tables
(or uses a dedicated test tenant) to make runs fully idempotent.

### 3. /configuracoes/profissionais page

The `hr-onboarding.spec.ts` verifies the doctor row in `/rh/funcionarios`
only. The `/configuracoes/profissionais` page does not exist yet (not created
in Sprint 18 scope). Add an assertion there once that page is built.

### 4. must_change_password middleware

After a successful login with a temporary/random password, the
`MustChangePasswordMiddleware` (T2) redirects the user to a change-password
page. E2E tests that log in as a newly-created employee (rather than the
seeded admin) will hit this redirect and need to handle it.
