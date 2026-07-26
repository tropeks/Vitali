"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LogOut,
  Bell,
  ChevronDown,
  ChevronRight,
  Menu,
  X,
  Search,
} from "lucide-react";
import type { UserDTO } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { useActiveModules } from "@/hooks/useHasModule";
import { LanguageSwitcher } from "@/components/shared/LanguageSwitcher";
import { PERMISSIONS, canSee } from "@/lib/permissions";
import { NAV_GROUPS, HOME_ITEM, type NavItem } from "./nav";
import CommandPalette from "./CommandPalette";
import {
  PERSONAS,
  applyPersona,
  loadPersona,
  savePersona,
  type PersonaId,
} from "@/lib/personas";

interface Props {
  user: UserDTO;
  children: React.ReactNode;
}

export default function DashboardShell({ user, children }: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Persona preset (soft UX layer over RBAC — never widens visibility).
  const [persona, setPersona] = useState<PersonaId>("todos");
  // User's manual header toggles, as `collapsed` booleans. Overrides the
  // persona default for a group; reset whenever the persona changes.
  const [collapsedOverrides, setCollapsedOverrides] = useState<Record<string, boolean>>({});
  const clinicalWorkspace = /^\/encounters\/[^/]+$/.test(pathname ?? "");

  const activeModules = useActiveModules();

  // Restore the persisted persona (keyed per user) once mounted.
  useEffect(() => {
    setPersona(loadPersona(user.id));
    setCollapsedOverrides({});
  }, [user.id]);

  // Three ordered gates (UI_NAVIGATION_IA.md §6), all UX-only. Module fails OPEN
  // while loading; superuser + permission never fail open.
  const itemVisible = (item: NavItem) => canSee(user, item, activeModules);

  // Groups (and their gated items) resolved for the current session. A group with
  // no visible items is dropped entirely. This is the HARD RBAC filter — the
  // persona layer below only reorders/collapses within this already-visible set.
  const visibleGroups = NAV_GROUPS.map((group) => ({
    label: group.label,
    items: group.items.filter(itemVisible),
  })).filter((group) => group.items.length > 0);

  // Persona layout: reorder + default expansion over the visible labels only.
  const layout = applyPersona(
    persona,
    visibleGroups.map((group) => group.label),
  );
  const orderedGroups = layout.order
    .map((label) => visibleGroups.find((group) => group.label === label))
    .filter((group): group is (typeof visibleGroups)[number] => group !== undefined);

  // A group is open when the user hasn't overridden it and the persona expands
  // it; a manual toggle wins.
  const groupOpen = (label: string) =>
    label in collapsedOverrides ? !collapsedOverrides[label] : layout.expanded.has(label);

  const toggleGroup = (label: string) =>
    setCollapsedOverrides((prev) => ({ ...prev, [label]: groupOpen(label) }));

  const changePersona = (next: PersonaId) => {
    setPersona(next);
    setCollapsedOverrides({});
    savePersona(user.id, next);
  };

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

            {orderedGroups.map((group) => {
              const open = groupOpen(group.label);
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
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-sm font-medium text-neu-ink">
              Vitali Health
            </span>
            {clinicalWorkspace && (
              <span className="hidden rounded-full border border-neu-brand/20 bg-neu-brand/10 px-2.5 py-1 text-xs font-semibold text-neu-brand sm:inline-flex">
                Atendimento
              </span>
            )}
          </div>

          {/* "Ir para…" — opens the ⌘K command palette */}
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            aria-label="Ir para… (busca global)"
            aria-keyshortcuts="Meta+K Control+K"
            className="flex flex-1 max-w-sm items-center gap-2 rounded-lg border border-neu-app bg-neu-input px-3 py-1.5 text-sm text-neu-inkMuted shadow-neu-inset transition-colors hover:text-neu-ink"
          >
            <Search size={15} className="shrink-0" aria-hidden />
            <span className="flex-1 text-left">Ir para…</span>
            <kbd className="hidden rounded border border-neu-app px-1.5 py-0.5 text-[10px] font-medium sm:block">
              ⌘K
            </kbd>
          </button>

          {/* Persona preset switcher (soft UX layer over RBAC) */}
          {!clinicalWorkspace && (
            <label className="hidden items-center gap-1.5 md:flex">
              <span className="sr-only">Perfil de navegação</span>
              <select
                aria-label="Perfil de navegação"
                value={persona}
                onChange={(event) => changePersona(event.target.value as PersonaId)}
                className="rounded-lg border border-neu-app bg-neu-input px-2 py-1.5 text-sm text-neu-ink shadow-neu-inset focus:outline-none focus:ring-2 focus:ring-neu-brand"
              >
                {PERSONAS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
          )}

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

      {/* Global "Ir para…" command palette (⌘K) — RBAC-scoped like the sidebar. */}
      <CommandPalette
        user={user}
        activeModules={activeModules}
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
      />
    </div>
  );
}
