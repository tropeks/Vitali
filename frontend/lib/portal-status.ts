/**
 * Patient-facing status vocabulary for the portal. Mirrors the canonical
 * staff `lib/operational-ui` maps, but the *labels* are softer
 * (patient-leigo language) and the colour palette is the same so the
 * shared `StatusBadge` works unchanged.
 */

import type { BadgeMeta } from "@/lib/operational-ui";

function meta(label: string, badgeClass: string, tone: BadgeMeta["tone"]): BadgeMeta {
  return { label, badgeClass, tone };
}

// Patient-friendly appointment status. The staff dashboard says "Em
// atendimento"; the portal says "Em andamento". "No show" becomes
// "Não compareceu" with empathetic framing.
export const PORTAL_APPOINTMENT_STATUS: Record<string, BadgeMeta> = {
  scheduled: meta("Agendada", "bg-slate-100 text-slate-700 border-slate-200", "neutral"),
  confirmed: meta("Confirmada", "bg-blue-100 text-blue-800 border-blue-200", "info"),
  waiting: meta("Aguardando você", "bg-yellow-100 text-yellow-800 border-yellow-200", "attention"),
  in_progress: meta("Em andamento", "bg-green-100 text-green-800 border-green-200", "success"),
  completed: meta("Concluída", "bg-slate-100 text-slate-600 border-slate-200", "neutral"),
  cancelled: meta("Cancelada", "bg-red-100 text-red-700 border-red-200", "critical"),
  no_show: meta("Não compareceu", "bg-red-100 text-red-700 border-red-200", "critical"),
};

// Same vocabulary as the prescription map but labelled for a leigo.
export const PORTAL_PRESCRIPTION_STATUS: Record<string, BadgeMeta> = {
  draft: meta("Rascunho", "bg-slate-100 text-slate-600 border-slate-200", "neutral"),
  signed: meta("Pronta para retirar", "bg-blue-100 text-blue-800 border-blue-200", "info"),
  partially_dispensed: meta(
    "Retirada parcial",
    "bg-yellow-100 text-yellow-800 border-yellow-200",
    "attention",
  ),
  dispensed: meta("Retirada concluída", "bg-green-100 text-green-800 border-green-200", "success"),
  cancelled: meta("Cancelada", "bg-red-100 text-red-700 border-red-200", "critical"),
};

export const PORTAL_ENCOUNTER_STATUS: Record<string, BadgeMeta> = {
  open: meta("Em aberto", "bg-yellow-100 text-yellow-800 border-yellow-200", "attention"),
  signed: meta("Assinada pelo médico", "bg-green-100 text-green-800 border-green-200", "success"),
  cancelled: meta("Cancelada", "bg-red-100 text-red-700 border-red-200", "critical"),
};

// Allergy severity rendered for the patient — "risco de vida" stays loud,
// but the soft-bg block in `ALLERGY_SEVERITY_BLOCK` works unchanged.
export const PORTAL_ALLERGY_SEVERITY: Record<string, BadgeMeta> = {
  life_threatening: meta(
    "Risco de vida",
    "bg-red-100 text-red-800 border-red-200",
    "critical",
  ),
  severe: meta("Grave", "bg-orange-100 text-orange-800 border-orange-200", "critical"),
  moderate: meta("Moderada", "bg-yellow-100 text-yellow-800 border-yellow-200", "attention"),
  mild: meta("Leve", "bg-green-100 text-green-800 border-green-200", "success"),
};

export function formatDateBR(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("pt-BR");
  } catch {
    return iso;
  }
}

export function formatDateTimeBR(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
