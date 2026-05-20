"use client";

import { StatusBadge } from "@/components/shared";
import PortalList from "@/components/portal/PortalList";
import { resolveBadgeMeta } from "@/lib/operational-ui";
import type { PortalEncounter } from "@/lib/portal-api";
import {
  PORTAL_ENCOUNTER_STATUS,
  formatDateTimeBR,
} from "@/lib/portal-status";

export default function PortalEncountersPage() {
  return (
    <PortalList<PortalEncounter>
      title="Meu prontuário"
      subtitle="Atendimentos assinados pelo médico — você só vê o que foi liberado."
      fetcher="getMyEncounters"
      empty={{
        title: "Nenhum atendimento assinado.",
        detail: "Assim que o médico assinar um atendimento, ele aparece aqui.",
      }}
      rowKey={(e) => e.id}
      renderRow={(e) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold text-slate-900">
              {formatDateTimeBR(e.encounter_date)}
            </p>
            <StatusBadge meta={resolveBadgeMeta(PORTAL_ENCOUNTER_STATUS, e.status)} />
          </div>
          {e.chief_complaint && (
            <p className="text-xs text-slate-600">
              <span className="font-medium text-slate-500">Motivo:</span>{" "}
              {e.chief_complaint}
            </p>
          )}
          {e.signed_at && (
            <p className="text-xs text-slate-500">
              Assinado em {formatDateTimeBR(e.signed_at)}
            </p>
          )}
        </div>
      )}
    />
  );
}
