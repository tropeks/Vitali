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
  FileText,
  Pill,
  Receipt,
  BarChart2,
  Sparkles,
  Settings,
  LogOut,
  Bell,
  ChevronDown,
  ChevronRight,
  Menu,
  X,
} from "lucide-react";
import type { UserDTO } from "@/lib/auth";
import { useActiveModules } from "@/hooks/useHasModule";

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
  { label: "Prontuário", href: "/dashboard/prontuario", icon: FileText, module: "emr" },
  {
    label: "Farmácia",
    href: "/farmacia",
    icon: Pill,
    module: "pharmacy",
    children: [
      { label: "Dispensar", href: "/farmacia/dispense" },
      { label: "Estoque", href: "/farmacia/stock" },
      { label: "Catálogo", href: "/farmacia/catalog" },
      { label: "Compras", href: "/farmacia/compras" },
    ],
  },
  { label: "Faturamento", href: "/billing", icon: Receipt, module: "billing" },
  { label: "Análise", href: "/billing/analytics", icon: BarChart2, module: "billing" },
  { label: "Inteligência Artificial", href: "/dashboard/ia", icon: Sparkles, module: "ai_tuss" },
  {
    label: "Configurações",
    href: "/configuracoes/assinatura",
    icon: Settings,
    adminOnly: true,
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
    await fetch("/api/auth/logout", { method: "POST" });
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
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      {/* Sidebar overlay (mobile) */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-64 bg-slate-900 text-white flex flex-col transition-transform lg:translate-x-0 lg:static lg:z-auto ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 border-b border-white/10">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center shrink-0">
            <span className="font-bold text-sm">V</span>
          </div>
          <span className="font-bold text-lg tracking-tight">Vitali</span>
          <button
            className="ml-auto lg:hidden text-slate-400 hover:text-white"
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
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  active
                    ? "bg-blue-600 text-white font-medium"
                    : "text-slate-400 hover:text-white hover:bg-white/5"
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
                              ? "bg-blue-500/30 text-white font-medium"
                              : "text-slate-400 hover:text-white hover:bg-white/5"
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
        <div className="px-4 py-4 border-t border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-xs font-bold shrink-0">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate">{user.full_name}</p>
              <p className="text-xs text-slate-400 capitalize">{user.role_name ?? "—"}</p>
            </div>
            <button
              onClick={handleLogout}
              className="text-slate-400 hover:text-red-400 transition-colors"
              title="Sair"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Topbar */}
        <header className="h-14 bg-white border-b border-slate-200 flex items-center px-4 gap-4 shrink-0">
          <button
            className="lg:hidden text-slate-500 hover:text-slate-900"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu size={20} />
          </button>

          {/* Tenant name placeholder */}
          <div className="flex-1">
            <span className="text-sm font-medium text-slate-700">
              Vitali Health
            </span>
          </div>

          {/* Notifications */}
          <button className="relative p-2 text-slate-500 hover:text-slate-900 rounded-lg hover:bg-slate-100">
            <Bell size={18} />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
          </button>

          {/* User dropdown */}
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen((v) => !v)}
              className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-slate-100 transition"
            >
              <div className="w-7 h-7 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-bold">
                {initials}
              </div>
              <span className="text-sm font-medium text-slate-700 hidden sm:block">
                {user.full_name.split(" ")[0]}
              </span>
              <ChevronDown size={14} className="text-slate-400" />
            </button>

            {userMenuOpen && (
              <>
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setUserMenuOpen(false)}
                />
                <div className="absolute right-0 top-full mt-1 w-48 bg-white rounded-xl shadow-lg border border-slate-200 z-20 py-1 text-sm">
                  <div className="px-3 py-2 border-b border-slate-100">
                    <p className="font-medium text-slate-900 truncate">{user.full_name}</p>
                    <p className="text-xs text-slate-500 truncate">{user.email}</p>
                  </div>
                  <Link
                    href="/dashboard/configuracoes/perfil"
                    className="block px-3 py-2 text-slate-700 hover:bg-slate-50"
                    onClick={() => setUserMenuOpen(false)}
                  >
                    Meu perfil
                  </Link>
                  <Link
                    href="/dashboard/configuracoes/senha"
                    className="block px-3 py-2 text-slate-700 hover:bg-slate-50"
                    onClick={() => setUserMenuOpen(false)}
                  >
                    Trocar senha
                  </Link>
                  {isAdmin && (
                    <Link
                      href="/configuracoes/assinatura"
                      className="block px-3 py-2 text-slate-700 hover:bg-slate-50"
                      onClick={() => setUserMenuOpen(false)}
                    >
                      Assinatura
                    </Link>
                  )}
                  <div className="border-t border-slate-100 mt-1" />
                  <button
                    onClick={handleLogout}
                    className="w-full text-left px-3 py-2 text-red-600 hover:bg-red-50"
                  >
                    Sair
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
