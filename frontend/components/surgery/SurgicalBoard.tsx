'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, Plus, RefreshCw } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import SurgicalCaseBlock from './SurgicalCaseBlock'
import ScheduleSurgeryModal from './ScheduleSurgeryModal'
import SurgicalCancelModal from './SurgicalCancelModal'
import {
  formatBoardDate,
  normalizeList,
  shiftDate,
  todayISO,
  type BoardCase,
  type BoardRoom,
  type FacilityOption,
  type ListResponse,
  type SurgicalBoardResponse,
} from './surgery-board-types'

interface SurgicalBoardProps {
  canSchedule: boolean
  canManage: boolean
}

interface RescheduleTarget {
  surgicalCase: BoardCase
  roomId: string
}

/**
 * Mapa cirúrgico — a day view of the operating rooms as columns, each holding
 * its scheduled cases as blocks coloured by status. Consumes GET
 * /surgical-cases/board/. A date navigator (prev / hoje / next) and an optional
 * facility filter drive the query. Scheduling actions (Agendar / Reagendar /
 * Confirmar / Cancelar) are gated by `canSchedule`.
 */
export default function SurgicalBoard({ canSchedule, canManage }: SurgicalBoardProps) {
  const [date, setDate] = useState<string>(todayISO())
  const [facilityId, setFacilityId] = useState('')
  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [rooms, setRooms] = useState<BoardRoom[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [actionError, setActionError] = useState('')

  const [scheduling, setScheduling] = useState(false)
  const [rescheduleFor, setRescheduleFor] = useState<RescheduleTarget | null>(null)
  const [cancelFor, setCancelFor] = useState<BoardCase | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    setActionError('')
    const params = new URLSearchParams({ date })
    if (facilityId) params.set('facility', facilityId)
    try {
      const data = await apiFetch<SurgicalBoardResponse>(
        `/api/v1/surgical-cases/board/?${params.toString()}`
      )
      setRooms(data?.rooms ?? [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [date, facilityId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    apiFetch<ListResponse<FacilityOption> | FacilityOption[]>(
      '/api/v1/organization/facilities/'
    )
      .then((data) => setFacilities(normalizeList(data)))
      .catch(() => setFacilities([]))
  }, [])

  const roomOptions = useMemo(
    () => rooms.map((r) => ({ id: r.id, code: r.code, name: r.name })),
    [rooms]
  )

  const afterAction = useCallback(() => {
    setScheduling(false)
    setRescheduleFor(null)
    setCancelFor(null)
    load()
  }, [load])

  async function confirmCase(c: BoardCase) {
    setActionError('')
    try {
      await apiFetch(`/api/v1/surgical-cases/${c.id}/confirm/`, { method: 'POST' })
      load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setActionError('Não é possível confirmar este caso na situação atual.')
      } else {
        setActionError('Não foi possível confirmar o caso. Tente novamente.')
      }
    }
  }

  function openReschedule(c: BoardCase) {
    const room = rooms.find((r) => r.cases.some((x) => x.id === c.id))
    setRescheduleFor({ surgicalCase: c, roomId: room?.id ?? '' })
  }

  const totalCases = rooms.reduce((sum, r) => sum + r.cases.length, 0)

  return (
    <div className="space-y-4">
      {/* Toolbar: date navigator + facility filter + Agendar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center rounded-lg border border-slate-200 bg-white">
            <button
              type="button"
              aria-label="Dia anterior"
              onClick={() => setDate((d) => shiftDate(d, -1))}
              className="p-2 text-slate-500 hover:bg-slate-50"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              type="button"
              onClick={() => setDate(todayISO())}
              className="border-x border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Hoje
            </button>
            <button
              type="button"
              aria-label="Próximo dia"
              onClick={() => setDate((d) => shiftDate(d, 1))}
              className="p-2 text-slate-500 hover:bg-slate-50"
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold capitalize text-neu-ink">
            <CalendarDays size={15} aria-hidden />
            {formatBoardDate(date)}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="surgery-facility-filter">
            Estabelecimento
          </label>
          <select
            id="surgery-facility-filter"
            aria-label="Estabelecimento"
            value={facilityId}
            onChange={(e) => setFacilityId(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="">Todos os estabelecimentos</option>
            {facilities.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          {canSchedule && (
            <button
              type="button"
              onClick={() => setScheduling(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
            >
              <Plus size={15} aria-hidden />
              Agendar
            </button>
          )}
        </div>
      </div>

      {actionError && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
          {actionError}
        </p>
      )}

      {loading ? (
        <SectionState
          title="Carregando mapa cirúrgico..."
          detail="Buscando as salas e os casos agendados do dia."
        />
      ) : error ? (
        <SectionState
          title="Erro ao carregar o mapa cirúrgico"
          detail="Não foi possível carregar as cirurgias do dia. Tente novamente."
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
      ) : rooms.length === 0 ? (
        <SectionState
          title="Nenhuma sala cirúrgica"
          detail="Cadastre salas cirúrgicas para este estabelecimento para ver o mapa do dia."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {rooms.map((room) => (
            <section
              key={room.id}
              aria-label={`Sala ${room.code}`}
              className="flex flex-col rounded-xl border border-slate-200 bg-neu-panel"
            >
              <header className="border-b border-slate-100 px-3 py-2">
                <div className="flex items-baseline gap-2">
                  <h3 className="text-sm font-semibold text-neu-ink">{room.name}</h3>
                  <span className="font-mono text-xs text-neu-inkMuted">{room.code}</span>
                </div>
                <p className="text-[11px] text-neu-inkMuted">
                  {room.cases.length === 0
                    ? 'Sem cirurgias'
                    : room.cases.length === 1
                      ? '1 cirurgia'
                      : `${room.cases.length} cirurgias`}
                </p>
              </header>
              <div className="flex-1 space-y-2 p-2">
                {room.cases.length === 0 ? (
                  <p className="px-1 py-4 text-center text-xs text-neu-inkMuted">
                    Nenhuma cirurgia agendada.
                  </p>
                ) : (
                  room.cases.map((c) => (
                    <SurgicalCaseBlock
                      key={c.id}
                      surgicalCase={c}
                      canSchedule={canSchedule}
                      onConfirm={confirmCase}
                      onReschedule={openReschedule}
                      onCancel={setCancelFor}
                    />
                  ))
                )}
              </div>
            </section>
          ))}
        </div>
      )}

      {!loading && !error && rooms.length > 0 && totalCases === 0 && (
        <p className="text-xs text-neu-inkMuted">
          Nenhuma cirurgia agendada para {formatBoardDate(date)}.
        </p>
      )}

      {scheduling && (
        <ScheduleSurgeryModal
          mode="schedule"
          rooms={roomOptions}
          defaultDate={date}
          canManage={canManage}
          onClose={() => setScheduling(false)}
          onDone={afterAction}
        />
      )}
      {rescheduleFor && (
        <ScheduleSurgeryModal
          mode="reschedule"
          rooms={roomOptions}
          defaultDate={date}
          canManage={canManage}
          caseId={rescheduleFor.surgicalCase.id}
          currentRoomId={rescheduleFor.roomId}
          currentStart={rescheduleFor.surgicalCase.scheduled_start}
          currentEnd={rescheduleFor.surgicalCase.scheduled_end}
          onClose={() => setRescheduleFor(null)}
          onDone={afterAction}
        />
      )}
      {cancelFor && (
        <SurgicalCancelModal
          caseId={cancelFor.id}
          patientName={cancelFor.patient.name}
          onClose={() => setCancelFor(null)}
          onCancelled={afterAction}
        />
      )}
    </div>
  )
}
