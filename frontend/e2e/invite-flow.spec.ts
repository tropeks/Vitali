/**
 * E2E: Invite-by-email flow
 *
 * Journey: Admin opens AddEmployeeModal -> selects "Enviar convite por e-mail"
 * auth mode -> creates employee -> retrieves the invitation JWT through the
 * E2E-only endpoint -> invitee visits /auth/set-password/<token> -> sets
 * password -> lands on /dashboard.
 *
 * The full path is active in CI when E2E_MODE=true. The token helper is
 * triple-gated server-side by E2E_MODE, superuser auth, and a *_test database.
 *
 * Prerequisites (see e2e/README.md):
 *   - Docker stack up (django + postgres + redis)
 *   - Frontend dev server running on :3000
 *   - Admin user seeded: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD
 */

import { test, expect, type APIResponse, type Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'AdminPass1!';

async function expectApiOk(response: APIResponse, label: string): Promise<void> {
  if (!response.ok()) {
    throw new Error(`${label} failed (${response.status()}): ${await response.text()}`);
  }
}

async function getAccessTokenFromSession(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  const accessToken = cookies.find((cookie) => cookie.name === 'access_token_js')?.value;
  expect(accessToken, 'admin login should set access_token_js').toBeTruthy();
  return accessToken!;
}

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

    // -- Navigate to HR page -------------------------------------------------
    await page.goto('/rh/funcionarios');
    await page.click('button:has-text("Adicionar Funcionário")');
    await expect(page.locator('text=Novo Funcionário')).toBeVisible();

    // -- Step 1: Personal info ----------------------------------------------
    await page.fill('#full_name', inviteeName);
    await page.fill('#email', inviteeEmail);
    await page.fill('#cpf', '22222222222');
    // Phone intentionally left blank — invite mode does not require it.

    await page.click('button:has-text("Próximo")');

    // -- Step 2: Role + contract (non-clinical role -> no council section) ---
    // "recepcao" is the default role; set it explicitly.
    await page.selectOption('#role', 'recepcao');
    await page.fill('#hire_date', '2026-01-01');
    await page.selectOption('#contract_type', 'clt');

    await page.click('button:has-text("Próximo")');

    // -- Step 3: Auth mode — invite by email ---------------------------------
    // Select the "Enviar convite por e-mail" radio (value="invite").
    await page.click('input[type="radio"][value="invite"]');

    // With auth_mode="invite" no password is needed; step3Valid should pass.
    await expect(page.locator('button:has-text("Cadastrar Funcionário")')).toBeEnabled();

    // -- Submit --------------------------------------------------------------
    await page.click('button:has-text("Cadastrar Funcionário")');

    // Success: "Funcionário criado ✓" + "Convite enviado ✓" toasts appear,
    // then the modal auto-closes and the table reloads showing the new employee.
    await expect(page.locator(`text=${inviteeEmail}`)).toBeVisible({ timeout: 20_000 });
  });

  test('invitee visits set-password link and lands on dashboard', async ({ page, request }) => {
    test.skip(
      !process.env.E2E_MODE,
      'Skipped: E2E_MODE env var not set. Configure E2E_MODE=1 + a _test DB to enable.'
    );

    const timestamp = Date.now();
    const inviteeEmail = `e2e.setpw+${timestamp}@vitali.com`;
    const inviteeName = `E2E SetPw ${timestamp}`;

    // -- Step 1: Admin creates employee with invite auth mode ----------------
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

    // -- Step 2: Retrieve invitation token via test-only endpoint ------------
    // Reuse the admin session created through the real login UI. This avoids a
    // second login request and keeps the protected helper on the same auth path
    // the product uses after sign-in.
    const access = await getAccessTokenFromSession(page);
    const tokenResp = await request.post('/api/v1/_test/invitations/issue-token/', {
      headers: { Authorization: `Bearer ${access}` },
      data: { user_email: inviteeEmail },
    });
    await expectApiOk(tokenResp, 'issue invitation token');
    const { token } = await tokenResp.json();
    expect(token).toBeTruthy();

    // -- Step 3: Invitee visits set-password link ----------------------------
    // Navigate as a fresh (unauthenticated) context — set-password is public.
    await page.context().clearCookies();
    await page.goto(`/auth/set-password/${token}`);
    await expect(page.locator('text=Defina sua senha')).toBeVisible({ timeout: 10_000 });

    await page.fill('#password', 'NovaSenha123!');
    await page.fill('#confirm', 'NovaSenha123!');
    await page.click('button:has-text("Definir senha e entrar")');

    // -- Step 4: Assert redirect to dashboard --------------------------------
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });
});
