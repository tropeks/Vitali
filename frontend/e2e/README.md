# Frontend E2E

Playwright covers the tenant-aware browser flows that must keep working across backend, frontend, Docker, and CI changes.

## Required Local Setup

Start the stack with Docker Compose, run migrations, create the test tenant/domain, seed roles, and create an admin user inside the tenant schema.

```bash
cp .env.example .env
docker compose --file docker-compose.yml up -d
docker compose --file docker-compose.yml exec -T django python manage.py migrate_schemas --shared
```

Create tenant/domain rows:

```bash
docker compose --file docker-compose.yml exec -T django python manage.py shell -c "
from apps.core.models import Tenant, Domain
public, _ = Tenant.objects.get_or_create(slug='public', defaults={'name': 'public'})
Domain.objects.get_or_create(domain='localhost', defaults={'tenant': public, 'is_primary': True})
clinic, _ = Tenant.objects.get_or_create(slug='testclinic', defaults={'name': 'Test Clinic'})
Domain.objects.get_or_create(domain='testclinic.localhost', defaults={'tenant': clinic, 'is_primary': True})
"
```

Seed the tenant roles before exercising HR onboarding:

```bash
docker compose --file docker-compose.yml exec -T django python manage.py create_default_roles --schema testclinic --overwrite
```

Create or refresh the E2E admin user:

```bash
docker compose --file docker-compose.yml exec -T django python manage.py shell -c "
from apps.core.models import Tenant, User, Role
from django_tenants.utils import schema_context
clinic = Tenant.objects.get(schema_name='testclinic')
with schema_context(clinic.schema_name):
    admin_role = Role.objects.get(name='admin')
    user = User.objects.filter(email='admin@test.com').first()
    if user is None:
        User.objects.create_superuser(
            email='admin@test.com',
            password='AdminPass1!',
            full_name='E2E Admin',
            role=admin_role,
        )
    else:
        user.full_name = user.full_name or 'E2E Admin'
        user.role = admin_role
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password('AdminPass1!')
        user.save(update_fields=['full_name', 'role', 'is_staff', 'is_superuser', 'is_active', 'password'])
"
```

Add `127.0.0.1 testclinic.localhost` to your hosts file, then run:

```bash
cd frontend
E2E_BASE_URL=http://testclinic.localhost:3000 \
E2E_BACKEND_URL=http://localhost:8000 \
E2E_MODE=true \
E2E_ADMIN_EMAIL=admin@test.com \
E2E_ADMIN_PASSWORD=AdminPass1! \
npx playwright test
```

## CI Contract

The `Frontend — E2E (Playwright)` job is a blocking CI gate. It must not use `continue-on-error`.

CI is responsible for:

- Booting the production frontend image without the dev Compose override.
- Running shared migrations.
- Creating the `public` and `testclinic` tenants/domains.
- Running `create_default_roles --schema testclinic --overwrite`.
- Creating `admin@test.com` in the `testclinic` schema with the `admin` role.
- Running Playwright with `E2E_MODE=true` against `http://testclinic.localhost:3000`.

`E2E_MODE=true` enables the test-only invitation token helper. The backend system check requires the database name to end with `_test`, which CI satisfies with `POSTGRES_DB=vitali_test`.

Invite acceptance must go through the Next route `/api/auth/set-password/<token>`, not directly through `/api/v1/auth/set-password/<token>/`, because the Next route converts the Django token response into the browser session cookies (`access_token`, `access_token_js`, `refresh_token`, and `vitali_user`) used by middleware and client API calls.

Protected app routes must either redirect unauthenticated users through middleware with a same-origin `next=` target or through the dashboard layout fallback. The `auth.spec.ts` contract covers `/patients`, login redirect behavior, logout cookie clearing, and rejection of external `next=` targets.

## Covered Specs

| Spec | Contract |
| --- | --- |
| `auth.spec.ts` | Login, logout, protected app route redirects, safe `next=` handling, and tenant shell access. |
| `invite-flow.spec.ts` | HR invite creation, test-only token retrieval, invite acceptance, and password setup. |
| `hr-onboarding.spec.ts` | HR employee onboarding through invite and generated-password modes. |

## HR Onboarding Data Contract

Playwright and the HR UI use these role keys:

- `admin`
- `medico`
- `enfermeiro`
- `recepcao`
- `faturista`
- `farmaceutico`
- `dentista`

`create_default_roles` must seed every key above in each tenant. `recepcao` is the canonical reception role for the product UI; `recepcionista` remains a legacy alias for existing tenants and permission checks.

Canonical employee enum values are:

- `employment_status`: `active`, `leave`, `terminated`
- `contract_type`: `clt`, `pj`, `estagio`, `temporary`

The API still normalizes legacy frontend aliases (`on_leave`, `estagiario`, `autonomo`) before validation so older clients fail gracefully into the canonical model values.

## Troubleshooting

- If HR onboarding submits but the employee never appears, check the backend response first. A missing role seed usually surfaces as `Role '<key>' não existe neste tenant.`
- If the invite setup test cannot fetch a token, verify `E2E_MODE=true`, a `_test` database name, and a superuser-authenticated request.
- If invite acceptance returns to `/login?next=%2Fdashboard`, verify the set-password page is calling `/api/auth/set-password/<token>` and that the response sets `vitali_user`.
- If tenant routing fails locally, verify `testclinic.localhost` resolves to `127.0.0.1` and that the `Domain` row exists in the public schema.
