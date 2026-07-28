import { describe, expect, it, beforeEach, vi } from "vitest";
import {
  applyPersona,
  loadPersona,
  savePersona,
  getPersona,
  PERSONAS,
} from "./personas";

// Natural NAV_GROUPS order (labels only), as the sidebar would hand them in.
const ALL_LABELS = [
  "Atendimento",
  "Apoio Diagnóstico",
  "Pessoas & Operações",
  "Painel de Setor",
  "Financeiro",
  "Suprimentos & Farmácia",
  "Concessão",
  "Administração",
  "Plataforma",
];

describe("applyPersona", () => {
  it("keeps natural order and expands everything for 'todos'", () => {
    const layout = applyPersona("todos", ALL_LABELS);
    expect(layout.order).toEqual(ALL_LABELS);
    expect([...layout.expanded].sort()).toEqual([...ALL_LABELS].sort());
  });

  it("floats the persona's groups to the top, in persona order, expanded", () => {
    const layout = applyPersona("faturamento", ALL_LABELS);
    // Faturamento prioritizes Financeiro then Administração.
    expect(layout.order.slice(0, 2)).toEqual(["Financeiro", "Administração"]);
    expect(layout.expanded.has("Financeiro")).toBe(true);
    expect(layout.expanded.has("Administração")).toBe(true);
    // Everything else sinks below, collapsed.
    expect(layout.expanded.has("Atendimento")).toBe(false);
    // No group is lost or duplicated.
    expect([...layout.order].sort()).toEqual([...ALL_LABELS].sort());
  });

  it("reorders relative to the default (a persona changes group order)", () => {
    const todos = applyPersona("todos", ALL_LABELS);
    const medico = applyPersona("medico", ALL_LABELS);
    expect(medico.order).not.toEqual(todos.order);
    expect(medico.order[0]).toBe("Atendimento");
  });

  it("NEVER reveals a group the user cannot see (no widening)", () => {
    // User lacks Financeiro entirely (RBAC already dropped it upstream).
    const visible = ALL_LABELS.filter((l) => l !== "Financeiro");
    const layout = applyPersona("faturamento", visible);
    // Faturamento prioritizes Financeiro — but it must not appear.
    expect(layout.order).not.toContain("Financeiro");
    expect(layout.expanded.has("Financeiro")).toBe(false);
    // Only visible labels come back.
    expect([...layout.order].sort()).toEqual([...visible].sort());
    // The next-priority visible group (Administração) floats up instead.
    expect(layout.order[0]).toBe("Administração");
  });

  it("only prioritizes groups that are visible, dropping hidden priorities", () => {
    const visible = ["Atendimento", "Administração"];
    const layout = applyPersona("gestao", visible);
    // Gestão prioritizes Financeiro, Pessoas & Operações, Painel de Setor,
    // Administração — only Administração is visible here.
    expect(layout.order).toEqual(["Administração", "Atendimento"]);
    expect(layout.expanded.has("Administração")).toBe(true);
    expect(layout.expanded.has("Atendimento")).toBe(false);
  });
});

describe("getPersona", () => {
  it("returns the requested persona and falls back to 'todos'", () => {
    expect(getPersona("medico").id).toBe("medico");
    // @ts-expect-error — exercising the runtime fallback with a bad id.
    expect(getPersona("bogus").id).toBe("todos");
  });

  it("exposes 'todos' as a no-priority default", () => {
    expect(PERSONAS.find((p) => p.id === "todos")?.groups).toEqual([]);
  });
});

describe("persistence (localStorage, keyed per user)", () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => (k in store ? store[k] : null),
      setItem: (k: string, v: string) => {
        store[k] = v;
      },
      removeItem: (k: string) => {
        delete store[k];
      },
      clear: () => {
        for (const k of Object.keys(store)) delete store[k];
      },
    });
  });

  it("defaults to 'todos' when nothing is stored", () => {
    expect(loadPersona("u-1")).toBe("todos");
  });

  it("persists and reloads the choice for a user", () => {
    savePersona("u-1", "enfermagem");
    expect(loadPersona("u-1")).toBe("enfermagem");
  });

  it("keys the choice per user (u-2 does not see u-1's persona)", () => {
    savePersona("u-1", "farmacia");
    expect(loadPersona("u-2")).toBe("todos");
  });

  it("ignores a corrupt stored value", () => {
    window.localStorage.setItem("vitali_persona:u-9", "not-a-persona");
    expect(loadPersona("u-9")).toBe("todos");
  });
});
