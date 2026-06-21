/**
 * next-intl request configuration (App Router, no i18n routing).
 *
 * Resolves the active locale from the `NEXT_LOCALE` cookie on every request
 * and loads the matching message catalog. Referenced by the next-intl plugin
 * in `next.config.mjs`.
 */
import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { LOCALE_COOKIE, resolveLocale } from "./config";

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const locale = resolveLocale(cookieStore.get(LOCALE_COOKIE)?.value);

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
