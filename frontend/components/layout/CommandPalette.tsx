"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Loader2, ArrowRight, User } from "lucide-react";
import type { UserDTO } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { visibleNavDestinations, type NavDestination } from "./nav";

/**
 * Global "Ir para…" command palette (⌘K / Ctrl+K), UI_NAVIGATION_IA.md §1.
 *
 * Two grouped sources:
 *   - "Navegação": NAV_GROUPS flattened to what {@link visibleNavDestinations}
 *     (i.e. `canSee`) lets THIS user see — never surfaces a hidden screen.
 *   - "Pacientes": debounced search against `/api/v1/patients/?search=<q>`.
 *
 * Keyboard-navigable (↑/↓/Enter/Esc), focus-trapped, substring/rank filtered,
 * accessible (role=dialog), and honours `prefers-reduced-motion`.
 */

interface PatientHit {
  id: string | number;
  full_name?: string;
  social_name?: string | null;
  medical_record_number?: string | null;
  age?: number | null;
}

type NavRow = { kind: "nav"; label: string; href: string };
type PatientRow = { kind: "patient"; label: string; sub: string | null; href: string };
type Row = NavRow | PatientRow;

interface Props {
  user: UserDTO;
  activeModules: string[] | null;
  /** Controlled open state. Omit for an uncontrolled palette (⌘K opens it). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/** Accent- and case-insensitive normalization for substring matching. */
function normalize(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/**
 * Substring filter + light ranking: keep destinations whose normalized label
 * contains the normalized query; rank earlier matches (and prefix matches)
 * higher. Empty query keeps the natural order.
 */
function filterNav(destinations: NavDestination[], query: string): NavDestination[] {
  const q = normalize(query.trim());
  if (!q) return destinations;
  return destinations
    .map((dest) => ({ dest, idx: normalize(dest.label).indexOf(q) }))
    .filter((entry) => entry.idx >= 0)
    .sort((a, b) => a.idx - b.idx || a.dest.label.length - b.dest.label.length)
    .map((entry) => entry.dest);
}

function patientLabel(p: PatientHit): string {
  return p.social_name?.trim() || p.full_name?.trim() || `Paciente ${p.id}`;
}

function patientSub(p: PatientHit): string | null {
  const parts: string[] = [];
  if (p.medical_record_number) parts.push(`Prontuário ${p.medical_record_number}`);
  if (typeof p.age === "number") parts.push(`${p.age} anos`);
  return parts.length ? parts.join(" · ") : null;
}

export default function CommandPalette({ user, activeModules, open, onOpenChange }: Props) {
  const router = useRouter();
  const isControlled = open !== undefined;
  const [internalOpen, setInternalOpen] = useState(false);
  const isOpen = isControlled ? (open as boolean) : internalOpen;

  const setOpen = useCallback(
    (next: boolean) => {
      if (!isControlled) setInternalOpen(next);
      onOpenChange?.(next);
    },
    [isControlled, onOpenChange],
  );

  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [patients, setPatients] = useState<PatientHit[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestRef = useRef(0);

  const reducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Nav destinations resolved for THIS user (same canSee gate as the sidebar).
  const navDestinations = useMemo(
    () => visibleNavDestinations(user, activeModules),
    [user, activeModules],
  );

  const navRows: NavRow[] = useMemo(
    () => filterNav(navDestinations, query).map((d) => ({ kind: "nav", ...d })),
    [navDestinations, query],
  );

  const patientRows: PatientRow[] = useMemo(
    () =>
      patients.map((p) => ({
        kind: "patient" as const,
        label: patientLabel(p),
        sub: patientSub(p),
        href: `/patients/${p.id}`,
      })),
    [patients],
  );

  const rows: Row[] = useMemo(() => [...navRows, ...patientRows], [navRows, patientRows]);

  // Global ⌘K / Ctrl+K listener — opens (or toggles) the palette from anywhere.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && (event.key === "k" || event.key === "K")) {
        event.preventDefault();
        setOpen(!isOpen);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, setOpen]);

  // Reset transient state and focus the input each time the palette opens.
  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setActiveIndex(0);
    setPatients([]);
    setLoadingPatients(false);
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [isOpen]);

  // Debounced patient search (>=2 chars). Sequence-guarded so a slow response
  // can't clobber a newer query (same pattern as RemoteCombobox).
  useEffect(() => {
    if (!isOpen) return;
    const term = query.trim();
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (term.length < 2) {
      setPatients([]);
      setLoadingPatients(false);
      return;
    }

    setLoadingPatients(true);
    debounceRef.current = setTimeout(() => {
      const current = ++requestRef.current;
      apiFetch<{ results?: PatientHit[] } | PatientHit[]>(
        `/api/v1/patients/?search=${encodeURIComponent(term)}&page_size=8`,
      )
        .then((data) => {
          if (current !== requestRef.current) return;
          const results = Array.isArray(data) ? data : data.results ?? [];
          setPatients(results);
          setLoadingPatients(false);
        })
        .catch(() => {
          if (current !== requestRef.current) return;
          setPatients([]);
          setLoadingPatients(false);
        });
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, isOpen]);

  // Keep the active row in range as the result set shrinks/grows.
  useEffect(() => {
    setActiveIndex((prev) => (rows.length === 0 ? 0 : Math.min(prev, rows.length - 1)));
  }, [rows.length]);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router, setOpen],
  );

  const onDialogKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((prev) => (rows.length === 0 ? 0 : (prev + 1) % rows.length));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((prev) => (rows.length === 0 ? 0 : (prev - 1 + rows.length) % rows.length));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const row = rows[activeIndex];
      if (row) go(row.href);
      return;
    }
    // Focus trap: keep Tab inside the (single-input) dialog.
    if (event.key === "Tab") {
      event.preventDefault();
      inputRef.current?.focus();
    }
  };

  if (!isOpen) return null;

  const transition = reducedMotion ? "" : "transition-opacity";

  return (
    <div
      className={`fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh] ${transition}`}
      onClick={() => setOpen(false)}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Ir para"
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/50 bg-neu-outer shadow-neu-elevated"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onDialogKeyDown}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-neu-app px-4 py-3">
          <Search size={18} className="shrink-0 text-neu-inkMuted" aria-hidden />
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded
            aria-controls="command-palette-list"
            aria-label="Buscar telas e pacientes"
            autoComplete="off"
            placeholder="Ir para… telas, pacientes"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            className="flex-1 bg-transparent text-sm text-neu-ink placeholder:text-neu-inkMuted focus:outline-none"
          />
          {loadingPatients && (
            <Loader2 size={16} className="shrink-0 animate-spin text-neu-brand" aria-label="Buscando" />
          )}
          <kbd className="hidden rounded border border-neu-app px-1.5 py-0.5 text-[10px] font-medium text-neu-inkMuted sm:block">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <ul
          id="command-palette-list"
          role="listbox"
          aria-label="Resultados"
          className="max-h-80 overflow-y-auto py-2"
        >
          {navRows.length > 0 && (
            <li role="presentation">
              <p className="px-4 py-1 text-[11px] font-semibold uppercase tracking-wide text-neu-inkMuted">
                Navegação
              </p>
            </li>
          )}
          {navRows.map((row, i) => {
            const index = i;
            const active = index === activeIndex;
            return (
              <li key={`nav-${row.href}`} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => go(row.href)}
                  className={`flex w-full items-center gap-3 px-4 py-2 text-left text-sm ${
                    active ? "bg-neu-panel text-neu-brand" : "text-neu-ink hover:bg-neu-panel/60"
                  }`}
                >
                  <ArrowRight size={15} className="shrink-0 text-neu-inkMuted" aria-hidden />
                  <span className="flex-1 truncate">{row.label}</span>
                </button>
              </li>
            );
          })}

          {patientRows.length > 0 && (
            <li role="presentation">
              <p className="px-4 py-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-neu-inkMuted">
                Pacientes
              </p>
            </li>
          )}
          {patientRows.map((row, i) => {
            const index = navRows.length + i;
            const active = index === activeIndex;
            return (
              <li key={`patient-${row.href}`} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => go(row.href)}
                  className={`flex w-full items-center gap-3 px-4 py-2 text-left text-sm ${
                    active ? "bg-neu-panel text-neu-brand" : "text-neu-ink hover:bg-neu-panel/60"
                  }`}
                >
                  <User size={15} className="shrink-0 text-neu-inkMuted" aria-hidden />
                  <span className="flex-1 truncate">
                    {row.label}
                    {row.sub && <span className="ml-2 text-xs text-neu-inkSoft">{row.sub}</span>}
                  </span>
                </button>
              </li>
            );
          })}

          {rows.length === 0 && !loadingPatients && (
            <li role="presentation" className="px-4 py-6 text-center text-sm text-neu-inkSoft">
              {query.trim() ? "Nenhum resultado encontrado." : "Digite para buscar."}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
