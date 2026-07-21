"use client";

import { StatusBadge } from "@/components/shared";
import PortalList from "@/components/portal/PortalList";
import { resolveBadgeMeta } from "@/lib/operational-ui";
import type { PortalAppointment } from "@/lib/portal-api";
import {
  PORTAL_APPOINTMENT_STATUS,
  formatDateTimeBR,
} from "@/lib/portal-status";

export default function PortalAppointmentsPage() {
  return (
    <PortalList<PortalAppointment>
      title="Minhas consultas"
      subtitle="Todas as consultas marcadas no seu histórico."
      fetcher="getMyAppointments"
      empty={{
        title: "Nenhuma consulta registrada.",
        detail: "Quando uma consulta for marcada na clínica ela aparece aqui.",
      }}
      rowKey={(a) => a.id}
      renderRow={(a) => (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-neu-ink">
              {formatDateTimeBR(a.start_time)}
            </p>
            <p className="text-xs text-neu-inkMuted">
              Tipo: {a.type || "consulta"}
            </p>
          </div>
          <StatusBadge meta={resolveBadgeMeta(PORTAL_APPOINTMENT_STATUS, a.status)} />
        </div>
      )}
    />
  );
}
