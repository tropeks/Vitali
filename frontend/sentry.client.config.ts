// Sentry client-side configuration for Next.js.
// This file is loaded automatically by @sentry/nextjs when running in the browser.
// See: https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  // Capture 10% of transactions for performance monitoring.
  // Increase this in staging to get more signal; keep it low in production
  // to avoid Sentry quota burns on high-traffic tenants.
  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,

  // Replay 1% of sessions normally, 100% of sessions that had an error.
  replaysSessionSampleRate: 0.01,
  replaysOnErrorSampleRate: 1.0,

  integrations: [
    Sentry.replayIntegration({
      // Mask all text and block all media for LGPD compliance.
      maskAllText: true,
      blockAllMedia: true,
    }),
  ],

  environment: process.env.NODE_ENV,

  // Do not send errors in local development.
  enabled: process.env.NODE_ENV !== "development",

  beforeSend(event) {
    // Strip PHI fields from user context for LGPD compliance.
    const phiKeys = new Set(["cpf", "patient_id", "patient_name", "phone", "email"]);
    if (event.user) {
      event.user = Object.fromEntries(
        Object.entries(event.user).filter(([k]) => !phiKeys.has(k))
      );
    }
    return event;
  },
});
