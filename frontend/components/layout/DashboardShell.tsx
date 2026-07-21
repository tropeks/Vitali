"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Users,
  Calendar,
  ClipboardList,
  Stethoscope,
  Activity,
  ScanLine,
  FlaskConical,
  CalendarX,
  Pill,
  Receipt,
  BarChart2,
  Settings,
  MessageCircle,
  LogOut,
  Bell,
  ChevronDown,
  ChevronRight,
  Menu,
  X,
} from "lucide-react";
import type { UserDTO } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { useActiveModules } from "@/hooks/useHasModule";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  /** If set, only shown when useHasModule(module) is true */
  module?: string;
  /** Admin-only item */
  adminOnly?: boolean;
  /** Sub-items rendered as an indented group beneath this item */
  children?: { label: string; href: string }[];
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Pacientes", href: "/patients", icon: Users, module: "emr" },
  { label: "Agenda", href: "/appointments", icon: Calendar, module: "emr" },
  { label: "Sala de Espera", href: "/waiting-room", icon: ClipboardList, module: "emr" },
  { label: "Consultas", href: "/encounters", icon: Stethoscope, module: "emr" },
  { label: "Laboratório", href: "/laboratorio", icon: FlaskConical, module: "emr" },
  { label: "Vitali Imagem", href: "/imagens", icon: ScanLine, module: "imaging" },
  { label: "Deterioração", href: "/deterioracao", icon: Activity, module: "emr" },
  { label: "Faltas", href: "/faltas", icon: CalendarX, module: "emr" },
  {
    label: "Farmácia",
    href: "/farmacia",
    icon: Pill,
    module: "pharmacy",
    children: [
      { label: "Cockpit", href: "/farmacia" },
      { label: "Dispensar", href: "/farmacia/dispense" },
      { label: "Estoque", href: "/farmacia/stock" },
      { label: "Catálogo", href: "/farmacia/catalog" },
      { label: "Compras", href: "/farmacia/compras" },
      { label: "Controlados", href: "/farmacia/controlados" },
    ],
  },
  {
    label: "RH",
    href: "/rh/funcionarios",
    icon: Users,
    module: "rh",
    adminOnly: true,
    children: [
      { label: "Funcionários", href: "/rh/funcionarios" },
    ],
  },
  { label: "Faturamento", href: "/billing", icon: Receipt, module: "billing" },
  { label: "Análise", href: "/billing/analytics", icon: BarChart2, module: "billing" },
  {
    label: "Configurações",
    href: "/configuracoes/assinatura",
    icon: Settings,
    adminOnly: true,
    children: [
      { label: "Assinatura", href: "/configuracoes/assinatura" },
      { label: "WhatsApp", href: "/configuracoes/whatsapp" },
      { label: "Inteligência Artificial", href: "/configuracoes/ai" },
      { label: "Profissionais", href: "/configuracoes/profissionais" },
      { label: "Formulário (doses)", href: "/configuracoes/farmacia/formulario" },
      { label: "Interações", href: "/configuracoes/farmacia/interacoes" },
      { label: "Suprimentos", href: "/configuracoes/farmacia/suprimentos" },
      { label: "Privacidade (LGPD)", href: "/configuracoes/privacidade" },
    ],
  },
];

interface Props {
  user: UserDTO;
  children: React.ReactNode;
}

export default function DashboardShell({ user, children }: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const clinicalWorkspace = /^\/encounters\/[^/]+$/.test(pathname ?? "");

  const activeModules = useActiveModules();
  // null = still loading; treat as all-visible (fail-open, no layout shift)
  const moduleVisible = (item: NavItem) =>
    !item.module || activeModules === null || activeModules.includes(item.module);

  const isAdmin = user.role_name?.toLowerCase() === "admin" ||
    user.role_name?.toLowerCase() === "administrador";

  const visibleItems = NAV_ITEMS.filter((item) => {
    if (!moduleVisible(item)) return false;
    if (item.adminOnly && !isAdmin) return false;
    return true;
  });

  const handleLogout = async () => {
    // apiFetch injects the JWT header and handles PASSWORD_CHANGE_REQUIRED (T12)
    await apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    router.push("/login");
    router.refresh();
  };

  const initials = user.full_name
    .split(" ")
    .slice(0, 2)
    .map((n) => n[0])
    .join("")
    .toUpperCase();

  return (
    <div className="flex h-screen bg-neu-app overflow-hidden">
      {/* Sidebar overlay (mobile) */}
      {sidebarOpen && !clinicalWorkspace && (
        <div
          className="fixed inset-0 z-20 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      {!clinicalWorkspace && (
        <aside
          className={`fixed inset-y-0 left-0 z-30 w-64 bg-neu-outer text-neu-ink border-r border-neu-app shadow-neu-panel flex flex-col transition-transform lg:translate-x-0 lg:static lg:z-auto ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          {/* Logo */}
          <div className="flex items-center gap-3 px-6 py-5 border-b border-neu-app">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-b from-neu-brand to-neu-brandDeep text-white shadow-neu-btn-primary flex items-center justify-center shrink-0">
              <span className="font-bold text-sm">V</span>
            </div>
            <span className="font-bold text-lg tracking-tight">Vitali</span>
            <button
              className="ml-auto lg:hidden text-neu-inkMuted hover:text-neu-ink"
              onClick={() => setSidebarOpen(false)}
            >
              <X size={18} />
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
            {visibleItems.map((item) => {
              const Icon = item.icon;
              const active =
                pathname === item.href || pathname.startsWith(item.href + "/");
              const hasChildren = item.children && item.children.length > 0;

              const linkEl = (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setSidebarOpen(false)}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm border transition-colors ${
                    active
                      ? "bg-neu-panel text-neu-brand font-medium border-white shadow-neu-panel"
                      : "border-transparent text-neu-inkSoft hover:text-neu-ink hover:bg-neu-panel/60"
                  }`}
                >
                  <Icon size={18} />
                  <span className="flex-1">{item.label}</span>
                  {hasChildren && (
                    <ChevronRight
                      size={14}
                      className={`transition-transform ${active ? "rotate-90" : ""}`}
                    />
                  )}
                </Link>
              );

              if (!hasChildren) return linkEl;

              return (
                <div key={item.href}>
                  {linkEl}
                  {active && (
                    <div className="ml-7 mt-0.5 space-y-0.5">
                      {item.children!.map((child) => {
                        const childActive =
                          pathname === child.href ||
                          pathname.startsWith(child.href + "/");
                        return (
                          <Link
                            key={child.href}
                            href={child.href}
                            onClick={() => setSidebarOpen(false)}
                            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors ${
                              childActive
                                ? "bg-neu-input text-neu-brand font-medium shadow-neu-inset"
                                : "text-neu-inkSoft hover:text-neu-ink hover:bg-neu-panel/60"
                            }`}
                          >
                            {child.label}
                          </Link>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </nav>

          {/* User footer */}
          <div className="px-4 py-4 border-t border-neu-app">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-gradient-to-b from-neu-brand to-neu-brandDeep text-white shadow-neu-btn-primary flex items-center justify-center text-xs font-bold shrink-0">
                {initials}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-neu-ink truncate">{user.full_name}</p>
                <p className="text-xs text-neu-inkSoft capitalize">{user.role_name ?? "—"}</p>
              </div>
              <button
                onClick={handleLogout}
                className="text-neu-inkMuted hover:text-neu-danger transition-colors"
                title="Sair"
              >
                <LogOut size={16} />
              </button>
            </div>
          </div>
        </aside>
      )}

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Topbar */}
        <header className="h-14 bg-neu-outer border-b border-neu-app shadow-neu-panel flex items-center px-4 gap-4 shrink-0">
          {!clinicalWorkspace && (
            <button
              className="lg:hidden text-neu-inkSoft hover:text-neu-ink"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu size={20} />
            </button>
          )}

          {/* Tenant name placeholder */}
          <div className="flex flex-1 items-center gap-3 min-w-0">
            <span className="text-sm font-medium text-neu-ink">
              Vitali Health
            </span>
            {clinicalWorkspace && (
              <span className="hidden rounded-full border border-neu-brand/20 bg-neu-brand/10 px-2.5 py-1 text-xs font-semibold text-neu-brand sm:inline-flex">
                Atendimento
              </span>
            )}
          </div>

          {/* Language */}
          <LanguageSwitcher />

          {/* Notifications */}
          <button className="relative p-2 text-neu-inkSoft hover:text-neu-ink rounded-lg hover:bg-neu-input">
            <Bell size={18} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-neu-danger rounded-full" />
          </button>

          {/* User dropdown */}
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen((v) => !v)}
              className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-neu-input transition"
            >
              <div className="w-7 h-7 rounded-full bg-gradient-to-b from-neu-brand to-neu-brandDeep shadow-neu-btn-primary flex items-center justify-center text-white text-xs font-bold">
                {initials}
              </div>
              <span className="text-sm font-medium text-neu-ink hidden sm:block">
                {user.full_name.split(" ")[0]}
              </span>
              <ChevronDown size={14} className="text-neu-inkMuted" />
            </button>

            {userMenuOpen && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setUserMenuOpen(false)}
                />
                <div className="absolute right-0 top-full mt-1 w-48 bg-neu-outer rounded-lg shadow-neu-elevated border border-white/50 z-20 py-1 text-sm">
                  <div className="px-3 py-2 border-b border-neu-app">
                    <p className="font-medium text-neu-ink truncate">{user.full_name}</p>
                    <p className="text-xs text-neu-inkSoft truncate">{user.email}</p>
                  </div>
                  <Link
                    href="/dashboard/configuracoes/perfil"
                    className="block px-3 py-2 text-neu-ink hover:bg-neu-panel"
                    onClick={() => setUserMenuOpen(false)}
                  >
                    Meu perfil
                  </Link>
                  <Link
                    href="/dashboard/configuracoes/senha"
                    className="block px-3 py-2 text-neu-ink hover:bg-neu-panel"
                    onClick={() => setUserMenuOpen(false)}
                  >
                    Trocar senha
                  </Link>
                  {isAdmin && (
                    <Link
                      href="/configuracoes/assinatura"
                      className="block px-3 py-2 text-neu-ink hover:bg-neu-panel"
                      onClick={() => setUserMenuOpen(false)}
                    >
                      Assinatura
                    </Link>
                  )}
                  <div className="border-t border-neu-app mt-1" />
                  <button
                    onClick={handleLogout}
                    className="w-full text-left px-3 py-2 text-neu-danger hover:bg-neu-danger/10"
                  >
                    Sair
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        {/* Page content */}
        <main className={`flex-1 overflow-y-auto ${clinicalWorkspace ? "p-0" : "p-6"}`}>{children}</main>
      </div>
    </div>
  );
}
