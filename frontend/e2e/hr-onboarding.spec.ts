/**
 * E2E: HR onboarding cascade — hire a doctor
 *
 * Journey: Admin opens AddEmployeeModal → fills 3 steps (personal info,
 * clinical role + council, random_password auth mode) → submits → verifies
 * the new doctor appears in the /rh/funcionarios table.
 *
 * Selector strategy: all inputs use id= attributes matching the form field
 * names (full_name, email, cpf, phone, role, hire_date, contract_type,
 * council_type, council_number, council_state, specialty). Step-nav buttons
 * are matched by visible text ("Próximo", "Cadastrar Funcionário").
 *
 * Prerequisites (see e2e/README.md):
 *   - Docker stack up (django + postgres + redis)
 *   - Frontend dev server running on :3000
 *   - Admin user seeded: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD
 */

import { test, expect } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'AdminPass1!';

test.describe('HR onboarding cascade — hire a doctor', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to login page and authenticate as admin.
    // The login form is built with react-hook-form and renders inputs that
    // carry name="email" and name="password" via the register() spread.
    await page.goto('/auth/login');
    await page.fill('input[name="email"]', ADMIN_EMAIL);
    await page.fill('input[name="password"]', ADMIN_PASSWORD);
    await page.click('button[type="submit"]');
    // After successful login the frontend redirects to /dashboard (or next= param).
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
  });

  test('admin hires a doctor end-to-end', async ({ page }) => {
    const timestamp = Date.now();
    const doctorEmail = `dr.teste+${timestamp}@vitali.com`;
    const doctorName = `Dr. Teste ${timestamp}`;

    // ── Navigate to the HR page ─────────────────────────────────────────────
    await page.goto('/rh/funcionarios');

    // Click the "+ Adicionar Funcionário" button to open the modal.
    // The page renders this button with text "+ Adicionar Funcionário".
    await page.click('button:has-text("Adicionar Funcionário")');

    // Modal should be visible (header says "Novo Funcionário").
    await expect(page.locator('text=Novo Funcionário')).toBeVisible();

    // ── Step 1: Personal info ───────────────────────────────────────────────
    // All Step 1 fields use id= attributes: full_name, email, cpf, phone.
    await page.fill('#full_name', doctorName);
    await page.fill('#email', doctorEmail);

    // CPF field has a formatter (formatCPF) that adds dots and dash as you type.
    // Filling 11 raw digits is enough; the formatter will decorate the display
    // value but the raw digits are what matters for step1Valid check.
    await page.fill('#cpf', '11111111111');
    await page.fill('#phone', '+5511999999999');

    // Proceed to Step 2.
    await page.click('button:has-text("Próximo")');

    // ── Step 2: Role + contract + council ───────────────────────────────────
    // Select "Médico" — value is "medico".
    await page.selectOption('#role', 'medico');

    await page.fill('#hire_date', '2026-01-01');

    // contract_type defaults to "clt" but set it explicitly to be safe.
    await page.selectOption('#contract_type', 'clt');

    // Council section appears because "medico" is a clinical role.
    await page.selectOption('#council_type', 'CRM');
    await page.fill('#council_number', String(timestamp));
    await page.selectOption('#council_state', 'SP');
    await page.fill('#specialty', 'Clínica Médica');

    // Proceed to Step 3.
    await page.click('button:has-text("Próximo")');

    // ── Step 3: Auth mode — random password ─────────────────────────────────
    // Select the "Gerar senha aleatória" radio. The radio input uses
    // name="auth_mode" value="random_password". We click its associated label
    // which wraps the radio (safer than clicking a partially-hidden input).
    await page.click('input[type="radio"][value="random_password"]');

    // Click "Gerar" to generate a random password (makes step3Valid pass).
    await page.click('button:has-text("Gerar")');

    // The generated password input should now be visible with a value.
    await expect(page.locator('#generated_password')).not.toHaveValue('');

    // ── Submit ──────────────────────────────────────────────────────────────
    // The submit button label is "Cadastrar Funcionário" (not "Criar funcionário").
    await page.click('button:has-text("Cadastrar Funcionário")');

    // Success: modal shows green toasts ("Funcionário criado ✓", "Profissional cadastrado ✓").
    // The modal auto-closes after 2.5 s. Either the toasts or the table row is
    // proof enough — we wait for the email to appear in the page.
    await expect(page.locator(`text=${doctorEmail}`)).toBeVisible({ timeout: 20_000 });

    // ── Post-submit: verify the employee row persists ───────────────────────
    // After modal closes and loadEmployees() re-fetches, the new doctor row
    // should be present in the /rh/funcionarios table.
    await page.goto('/rh/funcionarios');
    await expect(page.locator(`text=${doctorEmail}`)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(`text=${doctorName}`)).toBeVisible({ timeout: 10_000 });
  });
});
