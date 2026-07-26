'use client'

/**
 * RosterSlotGrid — calendar-ish view of a duty roster's plantões (RosterSlot),
 * grouped into one column per day. Mirrors the `RosterSlot` serializer
 * (fields="__all__"): id, roster, date, shift, start_time, end_time,
 * professional, employee, unit, created_at.
 */

export type RosterShift = 'morning' | 'afternoon' | 'night' | 'full'

export interface RosterSlot {
  id: string
  roster: string
  date: string
  shift: RosterShift
  start_time: string
  end_time: string
  professional: string | null
  employee: string | null
  unit: string | null
  created_at: string
}

export const SHIFT_LABELS: Record<RosterShift, string> = {
  morning: 'Manhã',
  afternoon: 'Tarde',
  night: 'Noite',
  full: 'Integral',
}

const SHIFT_TONE: Record<RosterShift, string> = {
  morning: 'border-amber-200 bg-amber-50 text-amber-800',
  afternoon: 'border-sky-200 bg-sky-50 text-sky-800',
  night: 'border-indigo-200 bg-indigo-50 text-indigo-800',
  full: 'border-emerald-200 bg-emerald-50 text-emerald-800',
}

/** 'HH:MM:SS' | 'HH:MM' → 'HH:MM'. */
function hm(time: string): string {
  return (time ?? '').slice(0, 5)
}

function formatDayHeader(date: string): string {
  try {
    return new Date(date + 'T00:00:00').toLocaleDateString('pt-BR', {
      weekday: 'short',
      day: '2-digit',
      month: '2-digit',
    })
  } catch {
    return date
  }
}

interface RosterSlotGridProps {
  slots: RosterSlot[]
  professionalNames?: Record<string, string>
  employeeNames?: Record<string, string>
}

export default function RosterSlotGrid({
  slots,
  professionalNames = {},
  employeeNames = {},
}: RosterSlotGridProps) {
  if (slots.length === 0) {
    return (
      <p className="text-xs text-neu-inkMuted italic px-1 py-2">Nenhum plantão nesta escala.</p>
    )
  }

  // Group by day, days sorted ascending, slots inside a day by start_time.
  const byDay = new Map<string, RosterSlot[]>()
  for (const slot of slots) {
    const bucket = byDay.get(slot.date)
    if (bucket) bucket.push(slot)
    else byDay.set(slot.date, [slot])
  }
  const days = Array.from(byDay.keys()).sort()

  function who(slot: RosterSlot): string {
    if (slot.professional) return professionalNames[slot.professional] ?? 'Profissional'
    if (slot.employee) return employeeNames[slot.employee] ?? 'Funcionário'
    return 'Sem responsável'
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-1">
      {days.map((day) => {
        const daySlots = [...(byDay.get(day) ?? [])].sort((a, b) =>
          a.start_time.localeCompare(b.start_time)
        )
        return (
          <div
            key={day}
            data-testid="roster-day-column"
            className="min-w-[160px] flex-shrink-0 rounded-lg border border-slate-200 bg-neu-panel"
          >
            <div className="border-b border-slate-100 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
              {formatDayHeader(day)}
            </div>
            <div className="space-y-2 p-2">
              {daySlots.map((slot) => (
                <div
                  key={slot.id}
                  className={`rounded-md border px-2.5 py-1.5 text-xs ${SHIFT_TONE[slot.shift]}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{SHIFT_LABELS[slot.shift]}</span>
                    <span className="tabular-nums opacity-80">
                      {hm(slot.start_time)}–{hm(slot.end_time)}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-[11px] opacity-90">{who(slot)}</div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
