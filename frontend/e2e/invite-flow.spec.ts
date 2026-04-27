/**
 * E2E: Invite-by-email flow
 *
 * Journey: Admin opens AddEmployeeModal → selects "Enviar convite por e-mail"
 * auth mode → creates employee → (TODO Sprint 19) retrieves the invitation JWT
 * token → invitee visits /auth/set-password/<token> → sets password → lands
 * on /dashboard.
 *
 * Current status:
 *   - The admin-creates-employee-with-invite portion is fully implemented.
 *   - The token-retrieval + set-password steps are marked test.skip with a
 *     TODO: we need a test-only endpoint (or Django management command) to
 *     extract the UserInvitation JWT token after creation. This is tracked as
 *     a Sprint 19 task.
 *
 * Prerequisites (see e2e/README.md):
 *   - Docker stack up (django + postgres + redis)
 *   - Frontend dev server running on :3000
 *   - Admin user seeded: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD
 */

import { test, expect } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'AdminPass1!';

test.describe('Invite flow — admin invites user by email', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate as admin.
    await page.goto('/login');
    await page.fill('input[name="email"]', ADMIN_EMAIL);
    await page.fill('input[name="password"]', ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
  });

  test('admin creates employee with invite auth mode', async ({ page }) => {
    const timestamp = Date.now();
    const inviteeEmail = `convidado+${timestamp}@vitali.com`;
    const inviteeName = `Convidado ${timestamp}`;

    // ── Navigate to HR page ─────────────────────────────────────────────────
    await page.goto('/rh/funcionarios');
    await page.click('button:has-text("Adicionar Funcionário")');
    await expect(page.locator('text=Novo Funcionário')).toBeVisible();

    // ── Step 1: Personal info ───────────────────────────────────────────────
    await page.fill('#full_name', inviteeName);
    await page.fill('#email', inviteeEmail);
    await page.fill('#cpf', '22222222222');
    // Phone intentionally left blank — invite mode does not require it.

    await page.click('button:has-text("Próximo")');

    // ── Step 2: Role + contract (non-clinical role → no council section) ────
    // "recepcao" is the default role; set it explicitly.
    await page.selectOption('#role', 'recepcao');
    await page.fill('#hire_date', '2026-01-01');
    await page.selectOption('#contract_type', 'clt');

    await page.click('button:has-text("Próximo")');

    // ── Step 3: Auth mode — invite by email ─────────────────────────────────
    // Select the "Enviar convite por e-mail" radio (value="invite").
    await page.click('input[type="radio"][value="invite"]');

    // With auth_mode="invite" no password is needed; step3Valid should pass.
    await expect(page.locator('button:has-text("Cadastrar Funcionário")')).toBeEnabled();

    // ── Submit ──────────────────────────────────────────────────────────────
    await page.click('button:has-text("Cadastrar Funcionário")');

    // Success: "Funcionário criado ✓" + "Convite enviado ✓" toasts appear,
    // then the modal auto-closes and the table reloads showing the new employee.
    await expect(page.locator(`text=${inviteeEmail}`)).toBeVisible({ timeout: 20_000 });
  });

  // ── Token-retrieval + set-password steps (Sprint 19: S-084) ──────────────
  //
  // POST /api/v1/_test/invitations/issue-token/ mints a fresh UserInvitation +
  // JWT for an existing user. Triple-gated:
  //   1. settings.E2E_MODE=True (env var, never set in deploy pipelines)
  //   2. request.user.is_superuser
  //   3. settings.DATABASES['default']['NAME'] ends with '_test'
  //
  // The test below is gated on process.env.E2E_MODE so it gracefully skips
  // in local dev environments that don't have E2E_MODE configured, while
  // running fully in CI once the env is provisioned.

  test('invitee visits set-password link and lands on dashboard', async ({ page, request }) => {
    // Skip locally until E2E_MODE=true + _test DB are configured in CI.
    // Remove this skip once the CI E2E environment sets E2E_MODE=1.
    test.skip(
      !process.env.E2E_MODE,
      'Skipped: E2E_MODE env var not set. Configure E2E_MODE=1 + a _test DB in CI to enable.'
    );

    const timestamp = Date.now();
    const inviteeEmail = `e2e.setpw+${timestamp}@vitali.com`;
    const inviteeName = `E2E SetPw ${timestamp}`;

    // ── Step 1: Admin creates employee with invite auth mode ────────────────
    await page.goto('/rh/funcionarios');
    await page.click('button:has-text("Adicionar Funcionário")');
    await expect(page.locator('text=Novo Funcionário')).toBeVisible();

    await page.fill('#full_name', inviteeName);
    await page.fill('#email', inviteeEmail);
    await page.fill('#cpf', '33333333333');

    await page.click('button:has-text("Próximo")');

    await page.selectOption('#role', 'recepcao');
    await page.fill('#hire_date', '2026-01-01');
    await page.selectOption('#contract_type', 'clt');

    await page.click('button:has-text("Próximo")');

    await page.click('input[type="radio"][value="invite"]');
    await expect(page.locator('button:has-text("Cadastrar Funcionário")')).toBeEnabled();
    await page.click('button:has-text("Cadastrar Funcionário")');

    await expect(page.locator(`text=${inviteeEmail}`)).toBeVisible({ timeout: 20_000 });

    // ── Step 2: Retrieve invitation token via test-only endpoint ────────────
    // Log in as admin to hit the superuser-gated endpoint.
    const loginResp = await request.post('/api/v1/auth/login', {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(loginResp.ok()).toBeTruthy();
    const { access } = await loginResp.json();

    const tokenResp = await request.post('/api/v1/_test/invitations/issue-token/', {
      headers: { Authorization: `Bearer ${access}` },
      data: { user_email: inviteeEmail },
    });
    expect(tokenResp.ok()).toBeTruthy();
    const { token } = await tokenResp.json();
    expect(token).toBeTruthy();

    // ── Step 3: Invitee visits set-password link ─────────────────────────────
    // Navigate as a fresh (unauthenticated) context — set-password is public.
    await page.context().clearCookies();
    await page.goto(`/auth/set-password/${token}`);
    await expect(page.locator('text=Defina sua senha')).toBeVisible({ timeout: 10_000 });

    await page.fill('#password', 'NovaSenha123!');
    await page.fill('#confirm', 'NovaSenha123!');
    await page.click('button:has-text("Definir senha e entrar")');

    // ── Step 4: Assert redirect to dashboard ────────────────────────────────
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
    await expect(page.locator('text=Dashboard')).toBeVisible();
  });
});
