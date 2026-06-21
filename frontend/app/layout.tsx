import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";
import "./globals.css";
import { CookieBanner } from "@/components/shared/CookieBanner";

export const metadata: Metadata = {
  title: "Vitali",
  description: "Plataforma Hospitalar SaaS — ERP + EMR + AI",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Locale comes from the NEXT_LOCALE cookie (see i18n/request.ts). Messages
  // are made available to every client component via NextIntlClientProvider.
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>
          {children}
          <CookieBanner />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
