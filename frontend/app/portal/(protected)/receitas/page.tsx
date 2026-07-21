"use client";

import { StatusBadge } from "@/components/shared";
import PortalList from "@/components/portal/PortalList";
import { resolveBadgeMeta } from "@/lib/operational-ui";
import type { PortalPrescription } from "@/lib/portal-api";
import {
  PORTAL_PRESCRIPTION_STATUS,
  formatDateTimeBR,
} from "@/lib/portal-status";

export default function PortalPrescriptionsPage() {
  return (
    <PortalList<PortalPrescription>
      title="Minhas receitas"
      subtitle="Receitas emitidas pelo seu médico — guarde o número para retirar na farmácia."
      fetcher="getMyPrescriptions"
      empty={{
        title: "Nenhuma receita emitida.",
        detail:
          "Receitas só aparecem aqui depois de assinadas pelo médico, no atendimento.",
      }}
      rowKey={(rx) => rx.id}
      renderRow={(rx) => (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-neu-ink">
                Receita #{rx.id.slice(0, 8)}
              </p>
              <p className="text-xs text-neu-inkMuted">
                {rx.signed_at
                  ? `Assinada em ${formatDateTimeBR(rx.signed_at)}`
                  : `Criada em ${formatDateTimeBR(rx.created_at)}`}
              </p>
            </div>
            <StatusBadge meta={resolveBadgeMeta(PORTAL_PRESCRIPTION_STATUS, rx.status)} />
          </div>
          {rx.notes && (
            <p className="text-xs text-neu-inkSoft">
              <span className="font-medium text-neu-inkMuted">Observações:</span>{" "}
              {rx.notes}
            </p>
          )}
        </div>
      )}
    />
  );
}
