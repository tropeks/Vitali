"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Globe, Check } from "lucide-react";
import { apiFetch } from "@/lib/api";
import {
  LOCALE_COOKIE,
  localeLabels,
  locales,
  toBackendCode,
  type Locale,
} from "@/i18n/config";

/**
 * UI language selector. Switching a locale:
 *   1. persists the choice in the NEXT_LOCALE cookie (read by i18n/request.ts),
 *   2. best-effort syncs the authenticated user's preferred_language so Django's
 *      LocaleMiddleware serves matching backend translations (ignored when the
 *      caller is anonymous, e.g. on the login screen),
 *   3. refreshes server components so the new catalog renders immediately.
 */
export function LanguageSwitcher() {
  const t = useTranslations("language");
  const activeLocale = useLocale() as Locale;
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  function selectLocale(locale: Locale) {
    setOpen(false);
    if (locale === activeLocale) return;

    // 1 year, root path — mirrors next-intl's default cookie lifetime.
    document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;

    // Keep the backend user preference in sync; failures (e.g. anonymous user)
    // are non-fatal — the cookie alone already drives the frontend locale.
    apiFetch("/api/v1/users/me/language/", {
      method: "PATCH",
      body: JSON.stringify({ preferred_language: toBackendCode(locale) }),
    }).catch(() => {});

    startTransition(() => router.refresh());
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={pending}
        aria-label={t("label")}
        title={pending ? t("updating") : t("label")}
        className="relative p-2 text-slate-500 hover:text-slate-900 rounded-lg hover:bg-slate-100 disabled:opacity-50"
      >
        <Globe size={18} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 w-52 bg-white rounded-lg shadow-lg border border-slate-200 z-20 py-1 text-sm">
            <p className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400 border-b border-slate-100">
              {t("label")}
            </p>
            {locales.map((locale) => (
              <button
                key={locale}
                type="button"
                onClick={() => selectLocale(locale)}
                className="flex w-full items-center justify-between px-3 py-2 text-left text-slate-700 hover:bg-slate-50"
              >
                {localeLabels[locale]}
                {locale === activeLocale && (
                  <Check size={14} className="text-blue-600 shrink-0" />
                )}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
