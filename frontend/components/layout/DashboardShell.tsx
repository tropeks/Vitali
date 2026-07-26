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
  PackageOpen,
  Receipt,
  BarChart2,
  Settings,
  Building2,
  Landmark,
  ShoppingCart,
  Server,
  BookMarked,
  Gauge,
  Fingerprint,
  CheckSquare,
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
import { PERMISSIONS, canSee, type NavGate } from "@/lib/permissions";

interface NavItem extends NavGate {
  label: string;
  href: string;
  icon: React.ElementType;
  /** Sub-items rendered as an indented group beneath this item */
  children?: { label: string; href: string }[];
}

interface NavGroup {
  /** Domain label (pt-BR) — rendered as a collapsible section header. */
  label: string;
  items: NavItem[];
}

/**
 * Home launcher — always visible, outside the collapsible groups.
 */
const HOME_ITEM: NavItem = { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard };

/**
 * Domain-grouped navigation (UI_NAVIGATION_IA.md §2). Each item carries its own
 * visibility gate (`module` / `permissions` / `superuser`) evaluated by
 * {@link canSee}. `adminOnly` (role_name-based) is RETIRED — items now gate on a
 * real backend permission (see §6). Permissions come from `@/lib/permissions`.
 */
const NAV_GROUPS: NavGroup[] = [
  {
    label: "Atendimento",
    items: [
      {
        label: "Pacientes",
        href: "/patients",
        icon: Users,
        module: "emr",
        permissions: [PERMISSIONS.PATIENTS_READ, PERMISSIONS.PATIENTS_LIMITED_READ],
      },
      {
        label: "Agenda",
        href: "/appointments",
        icon: Calendar,
        module: "emr",
        permissions: [PERMISSIONS.SCHEDULE_READ],
        children: [{ label: "Lista de espera", href: "/appointments/waitlist" }],
      },
      {
        label: "Sala de Espera",
        href: "/waiting-room",
        icon: ClipboardList,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ, PERMISSIONS.SCHEDULE_READ],
      },
      {
        label: "Consultas",
        href: "/encounters",
        icon: Stethoscope,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ],
      },
      {
        label: "Deterioração",
        href: "/deterioracao",
        icon: Activity,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ],
      },
      {
        label: "Faltas",
        href: "/faltas",
        icon: CalendarX,
        module: "emr",
        permissions: [PERMISSIONS.SCHEDULE_READ],
      },
    ],
  },
  {
    label: "Apoio Diagnóstico",
    items: [
      {
        label: "Laboratório",
        href: "/laboratorio",
        icon: FlaskConical,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ],
      },
      {
        label: "Vitali Imagem",
        href: "/imagens",
        icon: ScanLine,
        module: "imaging",
        permissions: [PERMISSIONS.IMAGING_READ],
      },
    ],
  },
  {
    label: "Pessoas & Operações",
    items: [
      {
        label: "RH",
        href: "/rh/funcionarios",
        icon: Users,
        module: "rh",
        // HRAccessPermission: admin capability OR hr.manage (apps/hr/views.py).
        // Escala stays here until S-IA2 moves it to the Painel de Setor.
        permissions: [PERMISSIONS.HR_MANAGE, PERMISSIONS.ADMIN],
        children: [
          { label: "Funcionários", href: "/rh/funcionarios" },
          { label: "Escalas", href: "/rh/escalas" },
          { label: "Lotação", href: "/rh/lotacoes" },
          { label: "Afastamentos", href: "/rh/afastamentos" },
          { label: "Cargos", href: "/rh/cargos" },
          { label: "Dependentes", href: "/rh/dependentes" },
        ],
      },
    ],
  },
  {
    label: "Financeiro",
    items: [
      {
        label: "Faturamento",
        href: "/billing",
        icon: Receipt,
        module: "billing",
        permissions: [PERMISSIONS.BILLING_READ],
        children: [
          { label: "Guias", href: "/billing/guides" },
          { label: "Glosas", href: "/billing/glosas" },
          { label: "Lotes", href: "/billing/batches" },
          { label: "Tabelas de preço", href: "/billing/price-tables" },
        ],
      },
      {
        label: "Análise",
        href: "/billing/analytics",
        icon: BarChart2,
        module: "billing",
        permissions: [PERMISSIONS.BILLING_READ, PERMISSIONS.REPORTS_READ],
      },
      {
        label: "Financeiro",
        href: "/administracao/resultado-financeiro",
        icon: Landmark,
        // Contas a pagar/receber, DRE, conciliação — financial management.
        permissions: [PERMISSIONS.BILLING_FULL, PERMISSIONS.ADMIN],
        children: [
          { label: "Resultado (DRE)", href: "/administracao/resultado-financeiro" },
          { label: "Conciliação", href: "/administracao/conciliacao-financeira" },
          { label: "Contas a pagar", href: "/billing/contas-a-pagar" },
          { label: "Contas a receber", href: "/billing/contas-a-receber" },
          { label: "Tesouraria", href: "/billing/tesouraria" },
          { label: "Repasses médicos", href: "/billing/settlements" },
        ],
      },
    ],
  },
  {
    label: "Suprimentos & Farmácia",
    items: [
      {
        label: "Farmácia",
        href: "/farmacia",
        icon: Pill,
        module: "pharmacy",
        permissions: [PERMISSIONS.PHARMACY_READ],
        children: [
          { label: "Cockpit", href: "/farmacia" },
          { label: "Dispensar", href: "/farmacia/dispense" },
          { label: "Estoque", href: "/farmacia/stock" },
          { label: "Risco de estoque", href: "/farmacia/risco-estoque" },
          { label: "Catálogo", href: "/farmacia/catalog" },
          { label: "Compras", href: "/farmacia/compras" },
          { label: "Controlados", href: "/farmacia/controlados" },
        ],
      },
      {
        label: "Compras",
        href: "/administracao/compras",
        icon: ShoppingCart,
        permissions: [PERMISSIONS.PHARMACY_STOCK_MANAGE, PERMISSIONS.ADMIN],
        children: [{ label: "Entradas NF-e", href: "/administracao/compras/entradas-nfe" }],
      },
    ],
  },
  {
    label: "Concessão",
    items: [
      {
        label: "Concessão",
        href: "/concessao",
        icon: PackageOpen,
        module: "diagnostic_concession",
        children: [
          { label: "Ativos", href: "/concessao/ativos" },
          { label: "Contratos", href: "/concessao/contratos" },
          { label: "Logística", href: "/concessao/logistica" },
          { label: "Manutenção", href: "/concessao/manutencao" },
          { label: "P&L", href: "/concessao/pnl" },
        ],
      },
    ],
  },
  {
    label: "Administração",
    items: [
      {
        label: "Estrutura organizacional",
        href: "/administracao/organizacao",
        icon: Building2,
        permissions: [PERMISSIONS.ORGANIZATION_READ],
      },
      {
        label: "Identidade de pacientes",
        href: "/administracao/mpi",
        icon: Fingerprint,
        permissions: [PERMISSIONS.MPI_READ],
      },
      {
        label: "Aprovações",
        href: "/administracao/aprovacoes",
        icon: CheckSquare,
        permissions: [PERMISSIONS.WORKFLOW_READ, PERMISSIONS.WORKFLOW_APPROVE],
      },
      {
        label: "Configurações",
        href: "/configuracoes/assinatura",
        icon: Settings,
        permissions: [PERMISSIONS.ADMIN],
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
    ],
  },
  {
    label: "Plataforma",
    items: [
      { label: "Tenants", href: "/platform/tenants", icon: Server, superuser: true },
      { label: "Terminologia", href: "/platform/terminology", icon: BookMarked, superuser: true },
      { label: "Monitor", href: "/platform/monitor", icon: Gauge, superuser: true },
      { label: "Valor (wedge)", href: "/platform/wedge-value", icon: BarChart2, superuser: true },
      { label: "Telemetria", href: "/wedges/telemetry", icon: Activity, superuser: true },
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
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const clinicalWorkspace = /^\/encounters\/[^/]+$/.test(pathname ?? "");

  const activeModules = useActiveModules();

  // Three ordered gates (UI_NAVIGATION_IA.md §6), all UX-only. Module fails OPEN
  // while loading; superuser + permission never fail open.
  const itemVisible = (item: NavItem) => canSee(user, item, activeModules);

  // Groups (and their gated items) resolved for the current session. A group with
  // no visible items is dropped entirely.
  const visibleGroups = NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.filter(itemVisible),
  })).filter((group) => group.items.length > 0);

  const toggleGroup = (label: string) =>
    setCollapsedGroups((prev) => ({ ...prev, [label]: !prev[label] }));

  // Admin capability for the topbar dropdown — keyed off the non-forgeable
  // `admin` permission (not the user-settable role_name).
  const isAdmin = user.permissions?.includes(PERMISSIONS.ADMIN) ?? false;

  const renderNavItem = (item: NavItem) => {
    const Icon = item.icon;
    const active = pathname === item.href || pathname.startsWith(item.href + "/");
    const hasChildren = item.children && item.children.length > 0;

    const linkEl = (
      <Link
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

    if (!hasChildren) return <div key={item.href}>{linkEl}</div>;

    return (
      <div key={item.href}>
        {linkEl}
        {active && (
          <div className="ml-7 mt-0.5 space-y-0.5">
            {item.children!.map((child) => {
              const childActive =
                pathname === child.href || pathname.startsWith(child.href + "/");
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
  };

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
          <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
            {renderNavItem(HOME_ITEM)}

            {visibleGroups.map((group) => {
              const open = !collapsedGroups[group.label];
              return (
                <div key={group.label} className="pt-2">
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.label)}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted hover:text-neu-ink transition-colors"
                  >
                    <span className="flex-1 text-left">{group.label}</span>
                    <ChevronDown
                      size={13}
                      className={`transition-transform ${open ? "" : "-rotate-90"}`}
                    />
                  </button>
                  {open && (
                    <div className="mt-0.5 space-y-0.5">
                      {group.items.map((item) => renderNavItem(item))}
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
