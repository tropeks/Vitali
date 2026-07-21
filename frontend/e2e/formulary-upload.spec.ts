/**
 * E2E: Formulary CSV upload flow (D-T1, issue #114)
 *
 * Journey: Admin/pharmacist opens the dose-formulary upload page ->
 * selects a CSV -> previews the parsed rows -> confirms the import ->
 * sees the success state and is invited to validate the rules.
 *
 * The CSV is supplied inline (setInputFiles with a buffer) using FAKE-E2E drug
 * names; the import is idempotent so re-running the spec is safe.
 *
 * Prerequisites (see e2e/README.md):
 *   - Docker stack up (django + postgres + redis)
 *   - Frontend dev server running on :3000
 *   - Admin user seeded: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD
 */

import { test, expect } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'AdminPass1!';

const CSV_HEADER =
  'drug_name,drug_generic,strength_value,strength_unit,route,basis,dose_unit,' +
  'min_per_dose,max_per_dose,absolute_max_dose,min_per_kg,max_per_kg,max_per_day,' +
  'dose_role,enforcement,freq_min_per_day,freq_max_per_day,age_min_days,age_max_days,' +
  'weight_min_kg,weight_max_kg';

const CSV_BODY = [
  CSV_HEADER,
  'FAKE-E2E-Alpha,fake e2e alpha,10.000,mg,IV,fixed,mg,5,15,15,,,,maintenance,block,,,,,,',
  'FAKE-E2E-Beta,fake e2e beta,5.000,mg,PO,fixed,mg,2.5,10,10,,,,maintenance,advise,,,,,,',
].join('\n');

test.describe('Formulary CSV upload — preview and commit', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.fill('input[name="email"]', ADMIN_EMAIL);
    await page.fill('input[name="password"]', ADMIN_PASSWORD);

    const loginResponse = page.waitForResponse(
      (response) => response.url().endsWith('/api/auth/login'),
      { timeout: 30_000 },
    );
    await page.click('button[type="submit"]');
    const response = await loginResponse;
    expect(
      response.ok(),
      `admin login failed (${response.status()}): ${await response.text()}`,
    ).toBeTruthy();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 });
  });

  test('admin uploads, previews and confirms a formulary CSV', async ({ page }) => {
    await page.goto('/configuracoes/farmacia/formulario/upload');
    await expect(
      page.getByRole('heading', { name: 'Importar formulário (doses)' }),
    ).toBeVisible();

    // -- Select the CSV (hidden file input, fed inline) ----------------------
    await page.locator('input[type="file"]').setInputFiles({
      name: 'formulario-e2e.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(CSV_BODY, 'utf-8'),
    });
    await expect(page.locator('text=formulario-e2e.csv')).toBeVisible();

    // -- Preview -------------------------------------------------------------
    const previewResponse = page.waitForResponse(
      (r) => r.url().includes('/pharmacy/formulary/upload/preview/'),
      { timeout: 30_000 },
    );
    await page.click('button:has-text("Pré-visualizar")');
    const prev = await previewResponse;
    expect(prev.ok(), `preview failed (${prev.status()}): ${await prev.text()}`).toBeTruthy();

    // Parsed rows surface in the preview table.
    await expect(page.locator('text=FAKE-E2E-Alpha')).toBeVisible();
    await expect(page.locator('text=FAKE-E2E-Beta')).toBeVisible();

    // -- Confirm import ------------------------------------------------------
    const commitResponse = page.waitForResponse(
      (r) => r.url().includes('/pharmacy/formulary/upload/commit/'),
      { timeout: 30_000 },
    );
    await page.click('button:has-text("Confirmar importação")');
    const commit = await commitResponse;
    expect(commit.ok(), `commit failed (${commit.status()}): ${await commit.text()}`).toBeTruthy();

    // Success state + the call-to-action to validate the imported rules.
    await expect(page.locator('text=Importação concluída.')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('link', { name: 'Ir para validação de doses' })).toBeVisible();
  });
});
