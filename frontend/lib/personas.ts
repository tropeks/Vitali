/**
 * Persona presets — a SOFT UX layer over the RBAC-filtered sidebar
 * (UI_NAVIGATION_IA.md §1/§6, gate 3).
 *
 * A persona ONLY reorders and collapses the nav groups the user can already see;
 * it NEVER widens visibility. `canSee` (module + RBAC + superuser) remains the
 * hard filter in DashboardShell — the functions here operate exclusively on the
 * already-visible group labels handed to them, so a preset is structurally
 * incapable of revealing a group the user lacks permission for.
 *
 * The choice persists in localStorage, keyed per user.
 */

export type PersonaId =
  | "todos"
  | "medico"
  | "enfermagem"
  | "recepcao"
  | "faturamento"
  | "farmacia"
  | "gestao";

export interface Persona {
  id: PersonaId;
  /** pt-BR label for the top-bar switcher. */
  label: string;
  /**
   * Nav group labels this persona cares about, in priority order. These groups
   * (when visible) float to the top and start expanded; every other visible
   * group sinks below, collapsed. Must match NAV_GROUPS labels exactly.
   * `todos` intentionally lists none → natural order, all expanded.
   */
  groups: string[];
}

/**
 * Persona → prioritized group labels. Labels are the exact NAV_GROUPS `label`s
 * from components/layout/nav.tsx.
 */
export const PERSONAS: Persona[] = [
  { id: "todos", label: "Tudo", groups: [] },
  {
    id: "medico",
    label: "Médico",
    groups: ["Atendimento", "Apoio Diagnóstico", "Suprimentos & Farmácia"],
  },
  {
    id: "enfermagem",
    label: "Enfermagem",
    groups: ["Atendimento", "Painel de Setor", "Apoio Diagnóstico"],
  },
  {
    id: "recepcao",
    label: "Recepção",
    groups: ["Atendimento", "Financeiro"],
  },
  {
    id: "faturamento",
    label: "Faturamento",
    groups: ["Financeiro", "Administração"],
  },
  {
    id: "farmacia",
    label: "Farmácia",
    groups: ["Suprimentos & Farmácia", "Atendimento"],
  },
  {
    id: "gestao",
    label: "Gestão",
    groups: ["Financeiro", "Pessoas & Operações", "Painel de Setor", "Administração"],
  },
];

const PERSONA_BY_ID: Record<PersonaId, Persona> = Object.fromEntries(
  PERSONAS.map((p) => [p.id, p]),
) as Record<PersonaId, Persona>;

export function getPersona(id: PersonaId): Persona {
  return PERSONA_BY_ID[id] ?? PERSONA_BY_ID.todos;
}

export interface PersonaLayout {
  /** Visible group labels, reordered for the persona. */
  order: string[];
  /** Labels that should start expanded. All others start collapsed. */
  expanded: Set<string>;
}

/**
 * Reorder + decide expansion for a persona over the labels the user can already
 * see (natural NAV_GROUPS order, already RBAC-filtered by the caller).
 *
 * - Prioritized groups that ARE visible float up (in persona order) and start
 *   expanded. A prioritized group that is NOT in `visibleLabels` is simply
 *   dropped — a preset can never conjure a hidden group (no widening).
 * - Remaining visible groups keep their natural order below, collapsed.
 * - `todos` (no priorities) → natural order, everything expanded (today's
 *   behavior, unchanged).
 */
export function applyPersona(personaId: PersonaId, visibleLabels: string[]): PersonaLayout {
  const persona = getPersona(personaId);

  if (persona.groups.length === 0) {
    return { order: [...visibleLabels], expanded: new Set(visibleLabels) };
  }

  const visible = new Set(visibleLabels);
  // Only prioritized groups the user can actually see, in persona order.
  const prioritized = persona.groups.filter((label) => visible.has(label));
  const prioritizedSet = new Set(prioritized);
  const rest = visibleLabels.filter((label) => !prioritizedSet.has(label));

  return {
    order: [...prioritized, ...rest],
    expanded: new Set(prioritized),
  };
}

const STORAGE_PREFIX = "vitali_persona:";

function storageKey(userId: string | number): string {
  return `${STORAGE_PREFIX}${userId}`;
}

function isPersonaId(value: string | null): value is PersonaId {
  return value !== null && value in PERSONA_BY_ID;
}

/** Read the persisted persona for a user (defaults to `todos`). */
export function loadPersona(userId: string | number): PersonaId {
  if (typeof window === "undefined") return "todos";
  try {
    const raw = window.localStorage.getItem(storageKey(userId));
    return isPersonaId(raw) ? raw : "todos";
  } catch {
    return "todos";
  }
}

/** Persist the persona choice for a user. */
export function savePersona(userId: string | number, personaId: PersonaId): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(userId), personaId);
  } catch {
    // localStorage unavailable (private mode / quota) — non-fatal.
  }
}
