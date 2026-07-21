/**
 * i18n configuration — shared between the request config, middleware-free
 * locale resolution and the in-app language switcher.
 *
 * Vitali uses next-intl WITHOUT locale routing: there is no `/[locale]/...`
 * URL segment. The active locale is stored in the `NEXT_LOCALE` cookie and
 * mirrored to the authenticated user's `preferred_language` on the backend
 * (`PATCH /api/v1/users/me/language/`), so the Django `LocaleMiddleware` and
 * the Next.js UI stay in sync.
 */

/** BCP-47 tags used for `<html lang>` and message catalog filenames. */
export const locales = ["pt-BR", "pt-PT", "es", "en"] as const;

export type Locale = (typeof locales)[number];

/** Falls back here when no cookie / unsupported value is present. */
export const defaultLocale: Locale = "pt-BR";

/** Cookie that persists the user's UI language (next-intl default name). */
export const LOCALE_COOKIE = "NEXT_LOCALE";

/** Human-readable labels for the language switcher. */
export const localeLabels: Record<Locale, string> = {
  "pt-BR": "Português (Brasil)",
  "pt-PT": "Português (Portugal)",
  es: "Español",
  en: "English",
};

/**
 * Django advertises language codes in lowercase (`pt-br`, `pt-pt`, `es`, `en`).
 * Convert a frontend locale to the code expected by the backend endpoint.
 */
export function toBackendCode(locale: Locale): string {
  return locale.toLowerCase();
}

/** Normalize any incoming string to a supported locale (or the default). */
export function resolveLocale(value: string | undefined | null): Locale {
  if (!value) return defaultLocale;
  const exact = locales.find((l) => l === value);
  if (exact) return exact;
  // Accept backend lowercase codes (e.g. "pt-pt") and bare language ("pt").
  const lower = value.toLowerCase();
  const ci = locales.find((l) => l.toLowerCase() === lower);
  if (ci) return ci;
  const byLang = locales.find((l) => l.toLowerCase().startsWith(lower.split("-")[0]));
  return byLang ?? defaultLocale;
}
