'use client'

import { useMemo } from 'react'
import { hasPermission } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { PageShell, SectionState } from '@/components/shared'
import PsBoard from '@/components/emergency/PsBoard'
import { ACUITY_META, ACUITY_ORDER } from '@/components/emergency/ps-board-types'

/**
 * E4 — Pronto-Socorro: fila do PS por gravidade (classificação de risco
 * Manchester). The board reads `emergency.read`; abrir boletim / chamar /
 * desfecho are gated by `emergency.manage`, and a triagem needs
 * `emergency.classify`.
 */
export default function ProntoSocorroPage() {
  const canRead = useMemo(() => hasPermission(PERMISSIONS.EMERGENCY_READ), [])
  const canManage = useMemo(() => hasPermission(PERMISSIONS.EMERGENCY_MANAGE), [])
  const canClassify = useMemo(() => hasPermission(PERMISSIONS.EMERGENCY_CLASSIFY), [])

  if (!canRead) {
    return (
      <PageShell variant="operational">
        <SectionState
          title="Sem acesso ao pronto-socorro"
          detail="Você não tem permissão para visualizar a fila do PS (emergency.read)."
          tone="warning"
        />
      </PageShell>
    )
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Pronto-Socorro</h1>
        <p className="mt-0.5 text-sm text-neu-inkMuted">
          Fila por gravidade (classificação de risco Manchester). Abra boletins, classifique,
          chame e registre o desfecho conforme suas permissões.
        </p>
      </div>

      {/* Legenda de acuidade Manchester */}
      <div className="flex flex-wrap gap-2">
        {ACUITY_ORDER.map((level) => (
          <span
            key={level}
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${ACUITY_META[level].badgeClass}`}
          >
            {ACUITY_META[level].fullLabel}
          </span>
        ))}
      </div>

      <section aria-label="Fila do pronto-socorro" className="mt-2">
        <PsBoard canManage={canManage} canClassify={canClassify} />
      </section>
    </PageShell>
  )
}
