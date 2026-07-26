'use client'

import { StatusBadge } from '@/components/shared'
import type { DutyRoster } from './RosterFormModal'
import RosterSlotGrid, { type RosterSlot } from './RosterSlotGrid'

/**
 * RosterList — one card per DutyRoster, each embedding its RosterSlotGrid of
 * plantões. Purely presentational; the page owns data + modals.
 */

interface RosterListProps {
  rosters: DutyRoster[]
  slotsByRoster: Record<string, RosterSlot[]>
  facilityNames?: Record<string, string>
  professionalNames?: Record<string, string>
  employeeNames?: Record<string, string>
  onEdit: (roster: DutyRoster) => void
  onAddSlot: (roster: DutyRoster) => void
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString('pt-BR')
  } catch {
    return dateStr
  }
}

export default function RosterList({
  rosters,
  slotsByRoster,
  facilityNames = {},
  professionalNames = {},
  employeeNames = {},
  onEdit,
  onAddSlot,
}: RosterListProps) {
  return (
    <div className="space-y-4">
      {rosters.map((roster) => {
        const slots = slotsByRoster[roster.id] ?? []
        return (
          <div
            key={roster.id}
            className="rounded-lg border border-slate-200 bg-neu-panel p-4"
          >
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-semibold text-neu-ink">{roster.name}</h2>
                  <StatusBadge
                    meta={
                      roster.active
                        ? { label: 'Ativa', badgeClass: 'bg-green-50 border-green-200 text-green-700' }
                        : { label: 'Inativa', badgeClass: 'bg-slate-50 border-slate-200 text-slate-600' }
                    }
                  />
                </div>
                <p className="mt-0.5 text-xs text-neu-inkMuted">
                  {facilityNames[roster.facility] ?? 'Unidade'} ·{' '}
                  {formatDate(roster.start_date)} → {formatDate(roster.end_date)} ·{' '}
                  {slots.length} {slots.length === 1 ? 'plantão' : 'plantões'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onAddSlot(roster)}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-neu-brand transition-colors hover:bg-slate-50"
                >
                  + Plantão
                </button>
                <button
                  onClick={() => onEdit(roster)}
                  className="text-xs font-semibold text-neu-brand hover:underline"
                >
                  Editar
                </button>
              </div>
            </div>

            <RosterSlotGrid
              slots={slots}
              professionalNames={professionalNames}
              employeeNames={employeeNames}
            />
          </div>
        )
      })}
    </div>
  )
}
