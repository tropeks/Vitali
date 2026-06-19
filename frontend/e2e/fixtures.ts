import { test as base, expect } from '@playwright/test';

/**
 * Shared E2E fixtures.
 *
 * Pre-accepts the LGPD cookie banner for every test. The banner (added in S32)
 * renders as a `fixed bottom-0 left-0 right-0 z-50` overlay that covers
 * bottom-anchored controls — the sidebar "Sair" button and form submit buttons
 * like "Cadastrar paciente" — and intercepts their clicks. Because it appears via
 * a useEffect after mount, it also makes those clicks flaky (pass/fail depending
 * on render timing). Setting consent before any navigation keeps it hidden.
 *
 * Tests that specifically exercise the banner clear this key themselves before
 * navigating (see auth.spec.ts › Cookie Consent Banner).
 */
export const test = base.extend({
  // Param is named `runTest` (not the conventional `use`) to avoid eslint's
  // react-hooks/rules-of-hooks false positive — it reads `use(...)` inside a
  // function named `page` as the React `use` hook.
  page: async ({ page }, runTest) => {
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem('vitali_cookie_consent', 'true');
      } catch {
        /* localStorage unavailable in this context — best-effort suppression */
      }
    });
    await runTest(page);
  },
});

export { expect };
