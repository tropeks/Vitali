import { CheckCircle2, Circle } from 'lucide-react'
import {
  TIME_EVENT_ORDER,
  formatDateTime,
  type SurgicalTimeEntry,
} from './surgery-case-types'

interface Props {
  times: SurgicalTimeEntry[]
}

/**
 * Tempos cirúrgicos — the ordered 6-event intra-op timeline of a case. Each of
 * the canonical events (entrada → saída) is shown as recorded (with its
 * `recorded_at`) or pending. Presentational only; the intra-op panel fetches
 * the times and owns the gated "Registrar tempo" control.
 */
export default function SurgeryTimeline({ times }: Props) {
  const recorded = new Map<string, SurgicalTimeEntry>()
  for (const time of times) {
    // Keep the first recorded row per event (times are append-only, ordered).
    if (!recorded.has(time.event)) recorded.set(time.event, time)
  }

  return (
    <ol className="space-y-2" aria-label="Tempos cirúrgicos">
      {TIME_EVENT_ORDER.map((event) => {
        const entry = recorded.get(event.value)
        const done = Boolean(entry)
        return (
          <li
            key={event.value}
            className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${
              done ? 'border-green-200 bg-green-50' : 'border-slate-200 bg-white'
            }`}
          >
            {done ? (
              <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-green-600" />
            ) : (
              <Circle size={16} className="mt-0.5 shrink-0 text-slate-300" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900">{event.label}</p>
              <p className="mt-0.5 text-xs text-slate-500">
                {done ? formatDateTime(entry?.recorded_at) : 'Pendente'}
              </p>
              {entry?.notes ? (
                <p className="mt-1 text-xs text-slate-600">{entry.notes}</p>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
