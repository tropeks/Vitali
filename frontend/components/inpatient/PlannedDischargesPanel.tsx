'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import { formatDateTime, type PlannedResponse, type PlannedRow } from './inpatient-types'

interface PlannedDischargesPanelProps {
  /** Bumping this (from the page) forces a reload after an ADT action. */
  reloadToken?: number
}

/**
 * Altas previstas — internações ativas com alta planejada (P2-1), da mais
 * próxima para a mais distante. Consome GET /api/v1/admissions/planned/ (leitura
 * ADT, beds.read). Antecipa a rotatividade de leitos para a equipe/NIR.
 */
export default function PlannedDischargesPanel({ reloadToken = 0 }: PlannedDischargesPanelProps) {
  const [rows, setRows] = useState<PlannedRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const resp = await apiFetch<PlannedResponse>('/api/v1/admissions/planned/')
      setRows(resp?.planned ?? [])
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
    return (
      <SectionState
        title="Carregando altas previstas..."
        detail="Buscando as internações com alta planejada."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar altas previstas"
        detail="Não foi possível carregar as altas previstas. Tente novamente."
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

  if (rows.length === 0) {
    return (
      <SectionState
        title="Nenhuma alta prevista"
        detail="Nenhuma internação ativa tem alta planejada no momento."
      />
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-white bg-neu-panel">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-semibold text-neu-inkMuted">
            <th className="px-3 py-2">Paciente</th>
            <th className="px-3 py-2">Leito</th>
            <th className="px-3 py-2">Alta prevista</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.admission_id} className="border-b border-slate-100 last:border-0">
              <td className="px-3 py-2 text-neu-ink">{row.patient.name}</td>
              <td className="px-3 py-2 font-mono text-neu-inkSoft">
                {row.current_bed?.identifier ?? '—'}
              </td>
              <td className="px-3 py-2 text-neu-ink">
                {formatDateTime(row.expected_discharge_datetime)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
