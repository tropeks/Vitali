// Sentry server-side configuration for Next.js.
// This file is loaded automatically by @sentry/nextjs for Node.js runtime
// (API routes, Server Components, middleware).
// See: https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,

  environment: process.env.NODE_ENV,

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
