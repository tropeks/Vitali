'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { KpiTile, SectionState } from '@/components/shared'
import {
  bedStatusMeta,
  formatLos,
  formatPercent,
  type CensusResponse,
  type CensusRow,
  type OccupancyRow,
} from './inpatient-types'

interface CensusPanelProps {
  /** Bumped by the page after a bed action to refetch the census. */
  reloadToken?: number
}

/** Ordered subset of statuses worth surfacing in the per-unit occupancy strip. */
const OCCUPANCY_STATUS_ORDER = [
  'ocupado',
  'livre',
  'higienizacao',
  'reservado',
  'bloqueado',
  'interditado',
] as const

/**
 * Censo / ocupação — a KPI header per unit (occupancy_rate % + counts by
 * status) and the active-census list (paciente, leito, unidade, LOS em horas).
 * Consumes GET /admissions/census/.
 */
export default function CensusPanel({ reloadToken = 0 }: CensusPanelProps) {
  const [occupancy, setOccupancy] = useState<OccupancyRow[]>([])
  const [census, setCensus] = useState<CensusRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<CensusResponse>('/api/v1/admissions/census/')
      setOccupancy(data?.occupancy ?? [])
      setCensus(data?.census ?? [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, reloadToken])

  if (loading) {
    return <SectionState title="Carregando censo..." detail="Buscando a ocupação e as internações." />
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar o censo"
        detail="Não foi possível carregar o censo de internação. Tente novamente."
        tone="critical"
        action={
          <button
            onClick={load}
            className="inline-flex items-center gap-2 text-xs font-semibold text-red-700 hover:underline"
          >
            <RefreshCw size={13} />
            Tentar novamente
          </button>
        }
      />
    )
  }

  return (
    <div className="space-y-5">
      {occupancy.length === 0 ? (
        <SectionState
          title="Nenhuma unidade de internação"
          detail="Cadastre unidades e leitos para acompanhar a ocupação."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {occupancy.map((row) => (
            <KpiTile
              key={row.unit.id}
              label={`${row.unit.name} · ${row.unit.code}`}
              value={formatPercent(row.occupancy_rate)}
              tone={row.occupancy_rate >= 0.9 ? 'critical' : 'info'}
              hint={
                <span className="flex flex-wrap gap-x-2 gap-y-0.5">
                  <span>
                    {row.occupied}/{row.operational_beds} operacionais
                  </span>
                  {OCCUPANCY_STATUS_ORDER.map((status) => {
                    const n = row.status_counts?.[status] ?? 0
                    if (!n) return null
                    return (
                      <span key={status}>
                        {bedStatusMeta(status).label}: {n}
                      </span>
                    )
                  })}
                </span>
              }
            />
          ))}
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-neu-ink">Internados</h3>
        {census.length === 0 ? (
          <SectionState
            title="Nenhum paciente internado"
            detail="As internações ativas aparecerão aqui com o tempo de permanência (LOS)."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-neu-inkMuted">
                  <th className="py-2 pr-3 font-semibold">Paciente</th>
                  <th className="py-2 pr-3 font-semibold">Leito</th>
                  <th className="py-2 pr-3 font-semibold">Unidade</th>
                  <th className="py-2 pr-3 font-semibold">Permanência</th>
                </tr>
              </thead>
              <tbody>
                {census.map((row) => (
                  <tr key={row.admission_id} className="border-b border-slate-100">
                    <td className="py-2 pr-3 font-medium text-neu-ink">{row.patient.name}</td>
                    <td className="py-2 pr-3 font-mono text-neu-inkSoft">{row.bed.identifier}</td>
                    <td className="py-2 pr-3 text-neu-inkSoft">{row.unit.name}</td>
                    <td className="py-2 pr-3 text-neu-inkSoft">
                      {formatLos(row.los_hours)}{' '}
                      <span className="text-xs text-neu-inkMuted">({row.los_hours}h)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
