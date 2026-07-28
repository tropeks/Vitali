'use client'

import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, RefreshCw, Scissors } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import SurgeryIntraopPanel from './SurgeryIntraopPanel'
import {
  CASE_PRIORITY_META,
  CASE_STATUS_META,
  formatDateTime,
  normalizeList,
  type ListResponse,
  type OperatingRoomOption,
  type SurgicalCase,
  type SurgicalProcedure,
} from './surgery-case-types'

interface Props {
  patientId: string
  /** `surgery.read` — gates the read-only case list + intra-op timeline. */
  canRead: boolean
  /** `surgery.manage` — gates every intra-op write (times / checklist / team). */
  canManage: boolean
}

/**
 * Cirurgia panel (C5) — the patient chart's surgical surface. Lists the
 * patient's surgical cases (`GET /surgical-cases/?patient=`) with
 * status/priority/room/time + procedures, resolving room names via
 * `/operating-rooms/` and procedures via `/surgical-procedures/?case=`.
 * Selecting a case opens the {@link SurgeryIntraopPanel}. The read view requires
 * `surgery.read`; intra-op writes are gated further. The backend enforces every
 * gate regardless.
 */
export default function SurgeryCasePanel({ patientId, canRead, canManage }: Props) {
  const [cases, setCases] = useState<SurgicalCase[]>([])
  const [rooms, setRooms] = useState<Record<string, string>>({})
  const [procedures, setProcedures] = useState<Record<string, SurgicalProcedure[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!patientId || !canRead) return
    setLoading(true)
    setError(false)
    try {
      const casesData = await apiFetch<ListResponse<SurgicalCase> | SurgicalCase[]>(
        `/api/v1/surgical-cases/?patient=${patientId}`,
      )
      const list = normalizeList(casesData)
      setCases(list)

      const [roomsResult, ...procedureResults] = await Promise.allSettled([
        apiFetch<ListResponse<OperatingRoomOption> | OperatingRoomOption[]>(
          '/api/v1/operating-rooms/',
        ),
        ...list.map((surgicalCase) =>
          apiFetch<ListResponse<SurgicalProcedure> | SurgicalProcedure[]>(
            `/api/v1/surgical-procedures/?case=${surgicalCase.id}`,
          ),
        ),
      ])

      const roomLabels: Record<string, string> = {}
      if (roomsResult.status === 'fulfilled') {
        for (const room of normalizeList(roomsResult.value)) {
          roomLabels[room.id] = `${room.code} — ${room.name}`
        }
      }
      setRooms(roomLabels)

      const proceduresByCase: Record<string, SurgicalProcedure[]> = {}
      procedureResults.forEach((result, index) => {
        const surgicalCase = list[index]
        if (surgicalCase && result.status === 'fulfilled') {
          proceduresByCase[surgicalCase.id] = normalizeList(result.value)
        }
      })
      setProcedures(proceduresByCase)
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
        title="Sem acesso ao centro cirúrgico"
        detail="Você não tem permissão para visualizar dados cirúrgicos (surgery.read)."
      />
    )
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando cirurgias..."
        detail="Buscando os casos cirúrgicos do paciente."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar cirurgias"
        detail="Não foi possível carregar os casos cirúrgicos. Tente novamente."
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

  if (selectedId) {
    return (
      <SurgeryIntraopPanel
        caseId={selectedId}
        canManage={canManage}
        onBack={() => {
          setSelectedId(null)
          void load()
        }}
      />
    )
  }

  if (cases.length === 0) {
    return (
      <SectionState
        title="Sem cirurgia registrada"
        detail="Nenhum caso cirúrgico vinculado ao paciente foi carregado."
      />
    )
  }

  return (
    <ul className="space-y-2" aria-label="Casos cirúrgicos">
      {cases.map((surgicalCase) => {
        const statusMeta = CASE_STATUS_META[surgicalCase.status] ?? {
          label: surgicalCase.status,
          badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
        }
        const priorityMeta = CASE_PRIORITY_META[surgicalCase.priority] ?? {
          label: surgicalCase.priority,
          badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
        }
        const caseProcedures = procedures[surgicalCase.id] ?? []
        const roomLabel = surgicalCase.operating_room
          ? rooms[surgicalCase.operating_room] ?? 'Sala a definir'
          : 'Sala a definir'
        return (
          <li key={surgicalCase.id}>
            <button
              type="button"
              onClick={() => setSelectedId(surgicalCase.id)}
              className="flex w-full items-start justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-left hover:bg-blue-50"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Scissors size={15} className="shrink-0 text-blue-600" />
                  <StatusBadge meta={statusMeta} />
                  <StatusBadge meta={priorityMeta} />
                </div>
                <p className="mt-2 text-sm font-semibold text-slate-900">{roomLabel}</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {formatDateTime(surgicalCase.scheduled_start)}
                </p>
                <p className="mt-1 text-xs text-slate-600">
                  {caseProcedures.length === 0
                    ? 'Sem procedimento planejado'
                    : caseProcedures
                        .map(
                          (procedure) =>
                            `${procedure.tuss_code_value || 'TUSS'}${
                              procedure.quantity && procedure.quantity > 1
                                ? ` ×${procedure.quantity}`
                                : ''
                            }`,
                        )
                        .join(', ')}
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
