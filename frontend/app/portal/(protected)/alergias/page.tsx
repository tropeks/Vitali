"use client";

import { StatusBadge } from "@/components/shared";
import PortalList from "@/components/portal/PortalList";
import { resolveBadgeMeta } from "@/lib/operational-ui";
import type { PortalAllergy } from "@/lib/portal-api";
import { PORTAL_ALLERGY_SEVERITY } from "@/lib/portal-status";

export default function PortalAllergiesPage() {
  return (
    <PortalList<PortalAllergy>
      title="Minhas alergias"
      subtitle="Sempre informe estas alergias ao profissional de saúde antes de qualquer procedimento."
      fetcher="getMyAllergies"
      empty={{
        title: "Nenhuma alergia registrada.",
        detail:
          "Se você tem uma alergia conhecida, informe ao médico no próximo atendimento para registrarmos.",
      }}
      rowKey={(a) => a.id}
      renderRow={(a) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold text-neu-ink">{a.substance}</p>
            <StatusBadge
              meta={resolveBadgeMeta(PORTAL_ALLERGY_SEVERITY, a.severity)}
            />
          </div>
          {a.reaction && (
            <p className="text-xs text-neu-inkSoft">
              <span className="font-medium text-neu-inkMuted">Reação:</span>{" "}
              {a.reaction}
            </p>
          )}
          <p className="text-xs text-neu-inkMuted">
            Status: {a.status === "active" ? "Ativa" : a.status === "resolved" ? "Resolvida" : "Inativa"}
          </p>
        </div>
      )}
    />
  );
}
