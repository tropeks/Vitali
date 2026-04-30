/**
 * E2E: Authentication and protected-route gate
 *
 * Covers the tenant app shell contract that every other E2E journey depends on:
 * unauthenticated protected routes redirect to login with a safe next= target,
 * login establishes the dashboard session, authenticated users do not see login,
 * and logout clears the browser session before protected routes can be opened again.
 */

import { test, expect, type Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || 'AdminPass1!';

async function loginAsAdmin(page: Page, nextPath = '/dashboard'): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(nextPath)}`);
  await page.fill('input[name="email"]', ADMIN_EMAIL);
  await page.fill('input[name="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');
}

test.describe('Auth gate', () => {
  test('redirects unauthenticated protected app routes to login with next', async ({ page }) => {
    await page.goto('/patients?tab=ativos');

    await expect(page).toHaveURL(/\/login\?next=%2Fpatients%3Ftab%3Dativos/);
    await expect(page.getByRole('heading', { name: 'Acesse sua conta' })).toBeVisible();
  });

  test('sanitizes next, redirects authenticated login, and logs out cleanly', async ({ page }) => {
    await loginAsAdmin(page, 'https://example.com/phishing');

    await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
    expect(page.url()).not.toContain('example.com');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

    await page.goto('/login');
    await expect(page).toHaveURL(/\/dashboard/);

    await expect(page.getByTitle('Sair')).toBeVisible();
    await page.getByTitle('Sair').click();

    await page.waitForURL(/\/login/, { timeout: 15_000 });
    const cookieNames = (await page.context().cookies()).map((cookie) => cookie.name);
    expect(cookieNames).not.toContain('access_token_js');
    expect(cookieNames).not.toContain('vitali_user');

    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
  });
});
