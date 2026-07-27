'use client'

import { useMemo } from 'react'
import { hasPermission } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { PageShell, SectionState } from '@/components/shared'
import SurgicalBoard from '@/components/surgery/SurgicalBoard'
import { CASE_STATUS_META, PRIORITY_META } from '@/components/surgery/surgery-board-types'

/**
 * C4 — Centro Cirúrgico: mapa cirúrgico (surgical board) do dia.
 *
 * The board reads `surgery.read`; scheduling actions (Agendar / Reagendar /
 * Confirmar / Cancelar) are gated by `surgery.schedule`, and creating a brand
 * new case inside the Agendar flow additionally needs `surgery.manage`.
 */
export default function CentroCirurgicoPage() {
  const canRead = useMemo(() => hasPermission(PERMISSIONS.SURGERY_READ), [])
  const canSchedule = useMemo(() => hasPermission(PERMISSIONS.SURGERY_SCHEDULE), [])
  const canManage = useMemo(() => hasPermission(PERMISSIONS.SURGERY_MANAGE), [])

  if (!canRead) {
    return (
      <PageShell variant="operational">
        <SectionState
          title="Sem acesso ao centro cirúrgico"
          detail="Você não tem permissão para visualizar o mapa cirúrgico (surgery.read)."
          tone="warning"
        />
      </PageShell>
    )
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Centro Cirúrgico</h1>
        <p className="mt-0.5 text-sm text-neu-inkMuted">
          Mapa cirúrgico do dia por sala. Agende, reagende, confirme ou cancele cirurgias conforme
          suas permissões.
        </p>
      </div>

      {/* Legenda de situação + prioridade */}
      <div className="flex flex-wrap gap-2">
        {Object.entries(CASE_STATUS_META)
          .filter(([status]) => status !== 'cancelada')
          .map(([status, meta]) => (
            <span
              key={status}
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}
            >
              {meta.label}
            </span>
          ))}
        {Object.entries(PRIORITY_META)
          .filter(([, meta]) => meta.accent)
          .map(([priority, meta]) => (
            <span
              key={priority}
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}
            >
              {meta.label}
            </span>
          ))}
      </div>

      <section aria-label="Mapa cirúrgico" className="mt-2">
        <SurgicalBoard canSchedule={canSchedule} canManage={canManage} />
      </section>
    </PageShell>
  )
}
