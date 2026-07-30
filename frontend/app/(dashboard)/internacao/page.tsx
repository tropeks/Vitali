'use client'

import { useCallback, useMemo, useState } from 'react'
import { hasPermission } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { PageShell, SectionState } from '@/components/shared'
import BedBoard from '@/components/inpatient/BedBoard'
import CensusPanel from '@/components/inpatient/CensusPanel'
import PlannedDischargesPanel from '@/components/inpatient/PlannedDischargesPanel'
import { BED_STATUS_META } from '@/components/inpatient/inpatient-types'

/**
 * L4 — Painel de Internação: mapa de leitos (bed-board) + censo/ocupação.
 *
 * Both panels read `beds.read`; bed actions are gated per-permission
 * (adt.transfer / adt.discharge / adt.admit). A shared `reloadToken` keeps the
 * census in sync after a bed action performed on the map.
 */
export default function InternacaoPage() {
  const canRead = useMemo(() => hasPermission(PERMISSIONS.BEDS_READ), [])
  const canTransfer = useMemo(() => hasPermission(PERMISSIONS.ADT_TRANSFER), [])
  const canDischarge = useMemo(() => hasPermission(PERMISSIONS.ADT_DISCHARGE), [])
  const canRelease = useMemo(() => hasPermission(PERMISSIONS.BEDS_HOUSEKEEPING), [])

  const [reloadToken, setReloadToken] = useState(0)
  const refresh = useCallback(() => setReloadToken((n) => n + 1), [])

  if (!canRead) {
    return (
      <PageShell variant="operational">
        <SectionState
          title="Sem acesso ao painel de internação"
          detail="Você não tem permissão para visualizar o mapa de leitos e o censo (beds.read)."
          tone="warning"
        />
      </PageShell>
    )
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Painel de Internação</h1>
        <p className="mt-0.5 text-sm text-neu-inkMuted">
          Mapa de leitos por unidade e censo de ocupação. Transfira ou dê alta direto do leito
          conforme suas permissões.
        </p>
      </div>

      {/* Legenda de situação dos leitos */}
      <div className="flex flex-wrap gap-2">
        {Object.entries(BED_STATUS_META).map(([status, meta]) => (
          <span
            key={status}
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.cellClass}`}
          >
            {meta.label}
          </span>
        ))}
      </div>

      <section aria-label="Censo e ocupação">
        <CensusPanel reloadToken={reloadToken} />
      </section>

      <section aria-label="Altas previstas" className="mt-2">
        <h2 className="mb-3 text-lg font-semibold text-neu-ink">Altas previstas</h2>
        <PlannedDischargesPanel reloadToken={reloadToken} />
      </section>

      <section aria-label="Mapa de leitos" className="mt-2">
        <h2 className="mb-3 text-lg font-semibold text-neu-ink">Mapa de leitos</h2>
        <BedBoard
          canTransfer={canTransfer}
          canDischarge={canDischarge}
          // Admissão pelo mapa (bed-centric) ainda não tem fluxo dedicado — a
          // admissão acontece pelo prontuário (aba Internação, L5). Mantemos o
          // botão desligado aqui para não expor uma ação inerte.
          canAdmit={false}
          canRelease={canRelease}
          reloadToken={reloadToken}
          onChanged={refresh}
        />
      </section>
    </PageShell>
  )
}
