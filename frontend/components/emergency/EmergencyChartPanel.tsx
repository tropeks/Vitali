'use client'

import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, RefreshCw, Siren } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import EmergencyCaseDetail from './EmergencyCaseDetail'
import {
  acuityMeta,
  formatDateTime,
  labelOf,
  MODE_OF_ARRIVAL_OPTIONS,
  normalizeList,
  statusMeta,
  type EmergencyEncounter,
  type ListResponse,
} from './emergency-chart-types'

interface Props {
  patientId: string
  /** `emergency.read` — gates the read-only boletim list + history. */
  canRead: boolean
  /** `emergency.classify` — gates the Reclassificar action in the detail. */
  canClassify: boolean
  /** `emergency.manage` — gates the Desfecho action in the detail. */
  canManage: boolean
}

/**
 * Emergência panel (E5) — the patient chart's PS/emergency surface. Lists the
 * patient's boletins de emergência (`GET /emergency-encounters/?patient=`) with
 * status, meio de chegada, queixa and the current Manchester acuity (badge +
 * tempo-alvo). Selecting a boletim opens the {@link EmergencyCaseDetail} (arrival
 * data + append-only classification history + gated Reclassificar/Desfecho). The
 * read view requires `emergency.read`; writes are gated further. The backend
 * enforces every gate regardless.
 */
export default function EmergencyChartPanel({ patientId, canRead, canClassify, canManage }: Props) {
  const [boletins, setBoletins] = useState<EmergencyEncounter[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!patientId || !canRead) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse<EmergencyEncounter> | EmergencyEncounter[]>(
        `/api/v1/emergency-encounters/?patient=${patientId}`,
      )
      setBoletins(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId, canRead])

  useEffect(() => {
    load()
  }, [load])

  if (!canRead) {
    return (
      <SectionState
        title="Sem acesso à emergência"
        detail="Você não tem permissão para visualizar dados de emergência (emergency.read)."
      />
    )
  }

  if (selectedId) {
    return (
      <EmergencyCaseDetail
        boletimId={selectedId}
        canClassify={canClassify}
        canManage={canManage}
        onBack={() => {
          setSelectedId(null)
          void load()
        }}
      />
    )
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando emergência..."
        detail="Buscando os boletins de atendimento de emergência do paciente."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar emergência"
        detail="Não foi possível carregar os boletins de emergência. Tente novamente."
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

  if (boletins.length === 0) {
    return (
      <SectionState
        title="Sem boletim de emergência"
        detail="Nenhum atendimento de emergência vinculado ao paciente foi carregado."
      />
    )
  }

  return (
    <ul className="space-y-2" aria-label="Boletins de emergência">
      {boletins.map((boletim) => {
        const current = boletim.current_classification ?? null
        return (
          <li key={boletim.id}>
            <button
              type="button"
              onClick={() => setSelectedId(boletim.id)}
              className="flex w-full items-start justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-left hover:bg-blue-50"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Siren size={15} className="shrink-0 text-red-600" />
                  <StatusBadge meta={statusMeta(boletim.status)} />
                  <StatusBadge meta={acuityMeta(current?.acuity_level)} />
                  {current && (
                    <span className="text-xs text-slate-500">
                      Tempo-alvo {current.target_minutes} min
                    </span>
                  )}
                </div>
                <p className="mt-2 text-sm font-semibold text-slate-900">
                  {boletim.chief_complaint || 'Sem queixa registrada'}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {labelOf(MODE_OF_ARRIVAL_OPTIONS, boletim.mode_of_arrival)} ·{' '}
                  {formatDateTime(boletim.arrival_at)}
                </p>
              </div>
              <ChevronRight size={16} className="mt-1 shrink-0 text-slate-400" />
            </button>
          </li>
        )
      })}
    </ul>
  )
}
