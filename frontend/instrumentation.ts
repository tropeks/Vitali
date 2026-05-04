import * as Sentry from "@sentry/nextjs";

const PHI_KEYS = new Set(["cpf", "patient_id", "patient_name", "phone", "email"]);

type SentryContextEvent = {
  user?: Record<string, unknown>;
  extra?: Record<string, unknown>;
};

function stripPhi<T>(event: T): T {
  const contextEvent = event as T & SentryContextEvent;

  if (contextEvent.user) {
    contextEvent.user = Object.fromEntries(
      Object.entries(contextEvent.user).filter(([key]) => !PHI_KEYS.has(key)),
    );
  }
  if (contextEvent.extra) {
    contextEvent.extra = Object.fromEntries(
      Object.entries(contextEvent.extra).filter(([key]) => !PHI_KEYS.has(key)),
    );
  }
  return event;
}

export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs" && process.env.NEXT_RUNTIME !== "edge") {
    return;
  }

  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    tracesSampleRate: process.env.NODE_ENV === "production" ? 0.1 : 1.0,
    environment: process.env.NODE_ENV,
    enabled: process.env.NODE_ENV !== "development",
    beforeSend(event) {
      return stripPhi(event);
    },
  });
}

export const onRequestError = Sentry.captureRequestError;
