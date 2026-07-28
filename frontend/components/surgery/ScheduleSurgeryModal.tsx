'use client'

import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  isUnscheduled,
  normalizeList,
  PRIORITY_OPTIONS,
  type ListResponse,
  type PatientOption,
  type ProfessionalOption,
  type SurgicalCaseDTO,
} from './surgery-board-types'

interface RoomOption {
  id: string
  code: string
  name: string
}

interface ScheduleSurgeryModalProps {
  /** `schedule` slots a case for the first time; `reschedule` moves an existing one. */
  mode: 'schedule' | 'reschedule'
  /** Rooms to choose from — the board's rooms ({ id, code, name }). */
  rooms: RoomOption[]
  /** Board date (YYYY-MM-DD) used to seed the default time window. */
  defaultDate: string
  /** surgery.manage — enables the "novo caso" create sub-form (schedule mode). */
  canManage: boolean
  /** reschedule context — the case being moved and its current slot. */
  caseId?: string
  currentRoomId?: string
  currentStart?: string | null
  currentEnd?: string | null
  onClose: () => void
  onDone: () => void
}

/** datetime-local seed at HH:00 on the board date. */
function seedTime(date: string, hour: number): string {
  const hh = String(hour).padStart(2, '0')
  return `${date}T${hh}:00`
}

function isoToLocal(value?: string | null): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`
}

/**
 * Schedule / reschedule a surgical case into a room + time window.
 *
 * `reschedule` posts to `/surgical-cases/{id}/reschedule/`. `schedule` posts to
 * `/surgical-cases/{id}/schedule/`, where the case is either an existing
 * unscheduled one (picked from `/surgical-cases/?status=agendada`) or a brand
 * new one created on the fly (patient + surgeon + priority → `POST
 * /surgical-cases/`, requires surgery.manage). An overlap 409 from either
 * scheduling endpoint is surfaced as "conflito de horário na sala".
 */
export default function ScheduleSurgeryModal({
  mode,
  rooms,
  defaultDate,
  canManage,
  caseId,
  currentRoomId,
  currentStart,
  currentEnd,
  onClose,
  onDone,
}: ScheduleSurgeryModalProps) {
  const isReschedule = mode === 'reschedule'

  const [caseSource, setCaseSource] = useState<'existing' | 'new'>(
    canManage ? 'new' : 'existing'
  )
  const [unscheduled, setUnscheduled] = useState<SurgicalCaseDTO[]>([])
  const [existingCaseId, setExistingCaseId] = useState('')
  const [patient, setPatient] = useState<PatientOption | null>(null)
  const [surgeon, setSurgeon] = useState<ProfessionalOption | null>(null)
  const [priority, setPriority] = useState('eletiva')

  const [roomId, setRoomId] = useState(currentRoomId ?? '')
  const [start, setStart] = useState(
    isReschedule ? isoToLocal(currentStart) : seedTime(defaultDate, 8)
  )
  const [end, setEnd] = useState(
    isReschedule ? isoToLocal(currentEnd) : seedTime(defaultDate, 9)
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const loadUnscheduled = useCallback(async () => {
    try {
      const data = await apiFetch<ListResponse<SurgicalCaseDTO> | SurgicalCaseDTO[]>(
        '/api/v1/surgical-cases/?status=agendada'
      )
      setUnscheduled(normalizeList(data).filter(isUnscheduled))
    } catch {
      setUnscheduled([])
    }
  }, [])

  useEffect(() => {
    if (!isReschedule) void loadUnscheduled()
  }, [isReschedule, loadUnscheduled])

  const professionalLabel = (p: ProfessionalOption) =>
    p.user_name || (p.council_number ? `Registro ${p.council_number}` : p.id)

  async function submit() {
    if (!roomId) {
      setError('Selecione uma sala cirúrgica.')
      return
    }
    if (!start || !end) {
      setError('Informe o início e o fim do procedimento.')
      return
    }
    const window = {
      scheduled_start: new Date(start).toISOString(),
      scheduled_end: new Date(end).toISOString(),
    }
    setSaving(true)
    setError('')
    try {
      if (isReschedule) {
        await apiFetch(`/api/v1/surgical-cases/${caseId}/reschedule/`, {
          method: 'POST',
          body: JSON.stringify({ ...window, operating_room: roomId }),
        })
      } else {
        let targetCaseId = existingCaseId
        if (caseSource === 'new') {
          if (!patient || !surgeon) {
            setError('Selecione o paciente e o cirurgião do novo caso.')
            setSaving(false)
            return
          }
          const created = await apiFetch<{ id: string }>('/api/v1/surgical-cases/', {
            method: 'POST',
            body: JSON.stringify({
              patient: patient.id,
              surgeon: surgeon.id,
              priority,
            }),
          })
          targetCaseId = created.id
        }
        if (!targetCaseId) {
          setError('Selecione um caso a agendar.')
          setSaving(false)
          return
        }
        await apiFetch(`/api/v1/surgical-cases/${targetCaseId}/schedule/`, {
          method: 'POST',
          body: JSON.stringify({ ...window, operating_room: roomId }),
        })
      }
      onDone()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Conflito de horário na sala — escolha outro horário ou sala.')
      } else {
        setError('Não foi possível agendar. Revise os dados e tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={isReschedule ? 'Reagendar cirurgia' : 'Agendar cirurgia'}
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <CalendarClock size={18} className="text-blue-600" />
            <h2 className="text-base font-semibold text-slate-900">
              {isReschedule ? 'Reagendar cirurgia' : 'Agendar cirurgia'}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          {!isReschedule && (
            <>
              {canManage && (
                <div
                  role="radiogroup"
                  aria-label="Origem do caso"
                  className="flex gap-2"
                >
                  <button
                    type="button"
                    role="radio"
                    aria-checked={caseSource === 'new'}
                    onClick={() => setCaseSource('new')}
                    className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold ${
                      caseSource === 'new'
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-slate-200 text-slate-600'
                    }`}
                  >
                    Novo caso
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={caseSource === 'existing'}
                    onClick={() => setCaseSource('existing')}
                    className={`flex-1 rounded-lg border px-3 py-2 text-sm font-semibold ${
                      caseSource === 'existing'
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-slate-200 text-slate-600'
                    }`}
                  >
                    Caso existente
                  </button>
                </div>
              )}

              {caseSource === 'new' ? (
                <div className="space-y-3">
                  <RemoteCombobox<PatientOption>
                    label="Paciente"
                    endpoint="/api/v1/patients/"
                    value={patient}
                    getKey={(item) => item.id}
                    getLabel={(item) => item.full_name}
                    onChange={setPatient}
                    placeholder="Buscar paciente..."
                  />
                  <RemoteCombobox<ProfessionalOption>
                    label="Cirurgião"
                    endpoint="/api/v1/professionals/"
                    value={surgeon}
                    getKey={(item) => item.id}
                    getLabel={professionalLabel}
                    onChange={setSurgeon}
                    placeholder="Buscar cirurgião..."
                  />
                  <label className="block text-xs font-semibold text-slate-600">
                    Prioridade
                    <select
                      value={priority}
                      onChange={(e) => setPriority(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                    >
                      {PRIORITY_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              ) : (
                <label className="block text-xs font-semibold text-slate-600">
                  Caso a agendar
                  <select
                    aria-label="Caso a agendar"
                    value={existingCaseId}
                    onChange={(e) => setExistingCaseId(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  >
                    <option value="">
                      {unscheduled.length === 0
                        ? 'Nenhum caso sem agenda'
                        : 'Selecione um caso...'}
                    </option>
                    {unscheduled.map((c) => (
                      <option key={c.id} value={c.id}>
                        {`Caso #${c.id.slice(0, 8)} · ${c.priority}`}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}

          <label className="block text-xs font-semibold text-slate-600">
            Sala cirúrgica
            <select
              aria-label="Sala cirúrgica"
              value={roomId}
              onChange={(e) => setRoomId(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            >
              <option value="">Selecione uma sala...</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.code} — {r.name}
                </option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs font-semibold text-slate-600">
              Início
              <input
                type="datetime-local"
                aria-label="Início"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs font-semibold text-slate-600">
              Fim
              <input
                type="datetime-local"
                aria-label="Fim"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving
              ? 'Salvando...'
              : isReschedule
                ? 'Reagendar'
                : 'Agendar'}
          </button>
        </div>
      </div>
    </div>
  )
}
