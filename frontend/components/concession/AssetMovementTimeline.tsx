'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  MOVEMENT_TYPE_LABEL,
  facilityName,
  formatDate,
  unwrap,
  type AssetMovement,
  type FacilityOption,
  type Listish,
} from './assetMeta'

/**
 * AssetMovementTimeline — per-asset history read from the append-only
 * asset-movements ledger, filtered to a single asset. The ledger endpoint
 * is not server-filtered, so we filter client-side by `asset` id.
 */

interface AssetMovementTimelineProps {
  assetId: string
  facilities: FacilityOption[]
}

function movementLocations(m: AssetMovement, facilities: FacilityOption[]): string {
  switch (m.movement_type) {
    case 'DEPLOYMENT':
      return `→ ${facilityName(m.to_facility, facilities)}`
    case 'RETRIEVAL':
      return `${facilityName(m.from_facility, facilities)} → Armazém`
    case 'TRANSFER':
      return `${facilityName(m.from_facility, facilities)} → ${facilityName(m.to_facility, facilities)}`
    case 'SWAP':
      return 'Troca de localização'
    default:
      return ''
  }
}

export default function AssetMovementTimeline({ assetId, facilities }: AssetMovementTimelineProps) {
  const [movements, setMovements] = useState<AssetMovement[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<Listish<AssetMovement>>(
        `/api/v1/concession/asset-movements/?asset=${encodeURIComponent(assetId)}`
      )
      // Ledger endpoint is not server-filtered — filter by asset client-side.
      setMovements(unwrap(data).filter((m) => m.asset === assetId))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [assetId])

  useEffect(() => {
    load()
  }, [load])

  if (loading) return <p className="text-sm text-neu-inkMuted">Carregando histórico...</p>

  if (error)
    return (
      <SectionState
        title="Erro ao carregar histórico."
        detail="Verifique sua conexão e tente novamente."
        tone="critical"
      />
    )

  if (movements.length === 0)
    return (
      <SectionState
        title="Nenhuma movimentação registrada."
        detail="As movimentações (implantação, recolhimento, transferência e troca) aparecerão aqui."
      />
    )

  return (
    <ol className="space-y-3">
      {movements.map((m) => (
        <li key={m.id} className="rounded-lg border border-slate-200 bg-neu-panel px-4 py-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-neu-ink">
              {MOVEMENT_TYPE_LABEL[m.movement_type]}
            </span>
            <span className="text-xs text-neu-inkMuted">{formatDate(m.created_at)}</span>
          </div>
          <p className="mt-1 text-xs text-neu-inkSoft">{movementLocations(m, facilities)}</p>
          {m.notes && <p className="mt-1 text-xs text-neu-inkMuted">{m.notes}</p>}
        </li>
      ))}
    </ol>
  )
}
