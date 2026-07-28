import { StatusBadge, SectionState } from '@/components/shared'
import { EVENT_TYPE_META, formatDateTime, type AdmissionEvent } from './admission-types'

interface Props {
  events: AdmissionEvent[]
  /** bed id → identifier, resolved from `/beds/board/` (optional enrichment). */
  bedLabels?: Record<string, string>
}

function bedLabel(id: string | null | undefined, labels?: Record<string, string>): string | null {
  if (!id) return null
  return labels?.[id] ?? `Leito ${id.slice(0, 8)}`
}

/**
 * ADT timeline — the append-only admit/transfer/discharge history for a stay
 * (`/admission-events/?admission=<id>`). Presentational only; the panel fetches.
 */
export default function AdmissionTimeline({ events, bedLabels }: Props) {
  if (events.length === 0) {
    return (
      <SectionState
        title="Sem eventos ADT"
        detail="Admissão, transferências e alta aparecerão aqui em ordem cronológica."
      />
    )
  }

  return (
    <ol className="space-y-3">
      {events.map((event) => {
        const meta = EVENT_TYPE_META[event.event_type] ?? {
          label: event.event_type,
          badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
        }
        const from = bedLabel(event.from_bed, bedLabels)
        const to = bedLabel(event.to_bed, bedLabels)
        return (
          <li
            key={event.id}
            className="rounded-lg border border-slate-200 bg-white px-4 py-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <StatusBadge meta={meta} />
                <p className="mt-1 text-xs text-slate-500">{formatDateTime(event.created_at)}</p>
              </div>
            </div>
            {(from || to) && (
              <p className="mt-2 text-xs text-slate-600">
                {from && to
                  ? `${from} → ${to}`
                  : to
                    ? `Leito: ${to}`
                    : `Leito de origem: ${from}`}
              </p>
            )}
            {event.reason && <p className="mt-1 text-sm text-slate-700">{event.reason}</p>}
          </li>
        )
      })}
    </ol>
  )
}
