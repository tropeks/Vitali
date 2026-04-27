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
    await page.goto('/auth/login');
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

  // ── Token-retrieval + set-password steps (Sprint 19 TODO) ─────────────────
  //
  // These steps require a test-only mechanism to read the UserInvitation JWT
  // that was created by the backend when the employee was inserted with
  // auth_mode="invite". Options being considered for Sprint 19:
  //
  //   a) Django management command:
  //        docker compose exec django python manage.py get_invitation_token <email>
  //   b) A DEBUG-gated API endpoint:
  //        GET /api/v1/auth/invitations/by-email/<email>/token/
  //        Only enabled when DEBUG=True (development/staging only).
  //   c) Celery task mock: intercept send_invitation_email task and capture
  //        the token from its kwargs before the email is dispatched.
  //
  // Until one of these is implemented, the set-password journey cannot be
  // driven by Playwright without hard-coding tokens or querying Django ORM
  // directly (which is outside the test harness scope).

  test('invitee visits set-password link and lands on dashboard — SKIPPED pending Sprint 19', async ({ page }) => {
    test.skip(
      true,
      'TODO (Sprint 19): needs a test-only endpoint or management command to retrieve ' +
      'the UserInvitation JWT token after admin creates an employee with auth_mode=invite. ' +
      'See e2e/README.md for the full gap description and proposed solutions.'
    );

    // The steps below are written out for reference so Sprint 19 only needs
    // to remove the test.skip above and supply the token retrieval mechanism.

    // const token = await retrieveInvitationToken(inviteeEmail); // Sprint 19
    // await page.goto(`/auth/set-password/${token}`);
    // await expect(page.locator('text=Defina sua senha')).toBeVisible();
    // await page.fill('#password', 'NovaSenha123!');
    // await page.fill('#confirm', 'NovaSenha123!');
    // await page.click('button:has-text("Definir senha e entrar")');
    // await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
    // await expect(page.locator('text=Dashboard')).toBeVisible();
  });
});
