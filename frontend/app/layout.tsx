import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vitali",
  description: "Plataforma Hospitalar SaaS — ERP + EMR + AI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
