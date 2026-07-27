'use client'

import { useMemo, useState } from 'react'
import { Clock, Plus } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { TIME_EVENT_ORDER, type SurgicalTimeEntry } from './surgery-case-types'

interface Props {
  caseId: string
  /** Already-recorded times of the case (drives the next-event suggestion). */
  times: SurgicalTimeEntry[]
  /** `surgery.manage` — gates the whole control. */
  canManage: boolean
  /** Called after a successful record so the panel can reload the timeline. */
  onRecorded: () => void
}

/**
 * "Registrar tempo" — the gated (`surgery.manage`) control that appends the next
 * intra-op time to a case (`POST /surgical-cases/{id}/record-time/`). It
 * pre-selects the next un-recorded event in the canonical order; recording it
 * may advance the case status (server-side). An out-of-order event → 409, which
 * surfaces as "fora de ordem". Renders nothing without `surgery.manage`.
 */
export default function RecordTimeControl({ caseId, times, canManage, onRecorded }: Props) {
  const recordedEvents = useMemo(
    () => new Set(times.map((time) => time.event)),
    [times],
  )
  const remaining = TIME_EVENT_ORDER.filter((event) => !recordedEvents.has(event.value))
  const [event, setEvent] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  if (!canManage) return null

  if (remaining.length === 0) {
    return (
      <p className="text-xs font-semibold text-green-700">Todos os tempos registrados.</p>
    )
  }

  // Default to the next event in order unless the user picked another remaining one.
  const selected = event || remaining[0].value

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      await apiFetch(`/api/v1/surgical-cases/${caseId}/record-time/`, {
        method: 'POST',
        body: JSON.stringify({ event: selected }),
      })
      setEvent('')
      onRecorded()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Tempo fora de ordem. Verifique a sequência dos tempos cirúrgicos.')
      } else {
        setError('Não foi possível registrar o tempo. Tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center gap-2">
        <Clock size={15} className="text-blue-600" />
        <span className="text-sm font-semibold text-slate-900">Registrar tempo</span>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
        <label className="block flex-1 text-xs font-semibold text-slate-600">
          Próximo tempo
          <select
            aria-label="Tempo cirúrgico"
            value={selected}
            onChange={(e) => setEvent(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            {remaining.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={submit}
          disabled={saving}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          <Plus size={15} />
          {saving ? 'Registrando...' : 'Registrar tempo'}
        </button>
      </div>
      {error && <p className="mt-2 text-xs font-semibold text-red-700">{error}</p>}
    </div>
  )
}
