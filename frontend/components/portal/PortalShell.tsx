"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays,
  ClipboardList,
  Heart,
  Menu,
  Pill,
  ShieldAlert,
  User,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";

interface NavItem {
  href: string;
  label: string;
  icon: typeof CalendarDays;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/portal", label: "Início", icon: Heart },
  { href: "/portal/agendamentos", label: "Consultas", icon: CalendarDays },
  { href: "/portal/prontuario", label: "Prontuário", icon: ClipboardList },
  { href: "/portal/receitas", label: "Receitas", icon: Pill },
  { href: "/portal/alergias", label: "Alergias", icon: ShieldAlert },
  { href: "/portal/perfil", label: "Perfil", icon: User },
];

interface PortalShellProps {
  userName: string;
  children: ReactNode;
}

export default function PortalShell({ userName, children }: PortalShellProps) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link href="/portal" className="flex items-center gap-2">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-base font-semibold text-white">
              V
            </span>
            <div>
              <div className="text-sm font-semibold text-slate-900">Vitali — Portal</div>
              <div className="hidden text-xs text-slate-500 sm:block">Olá, {userName}</div>
            </div>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden items-center gap-1 md:flex">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active =
                item.href === "/portal"
                  ? pathname === "/portal"
                  : pathname?.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    active
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  <Icon size={16} />
                  {item.label}
                </Link>
              );
            })}
            <form action="/api/auth/logout" method="post" className="ml-2">
              <button
                type="submit"
                className="rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-900"
              >
                Sair
              </button>
            </form>
          </nav>

          {/* Mobile toggle */}
          <button
            type="button"
            onClick={() => setOpen((s) => !s)}
            className="rounded-lg border border-slate-200 p-2 text-slate-700 md:hidden"
            aria-label="Abrir menu"
          >
            {open ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>

        {/* Mobile nav */}
        {open && (
          <nav className="border-t border-slate-100 md:hidden">
            <div className="mx-auto flex max-w-5xl flex-col gap-1 px-4 py-3">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                const active =
                  item.href === "/portal"
                    ? pathname === "/portal"
                    : pathname?.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className={`inline-flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium ${
                      active
                        ? "bg-blue-50 text-blue-700"
                        : "text-slate-700 hover:bg-slate-100"
                    }`}
                  >
                    <Icon size={18} />
                    {item.label}
                  </Link>
                );
              })}
              <form action="/api/auth/logout" method="post" className="mt-1">
                <button
                  type="submit"
                  className="w-full rounded-lg px-3 py-2.5 text-left text-sm font-medium text-slate-600 hover:bg-slate-100"
                >
                  Sair
                </button>
              </form>
            </div>
          </nav>
        )}
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6 sm:py-8">{children}</main>
    </div>
  );
}
