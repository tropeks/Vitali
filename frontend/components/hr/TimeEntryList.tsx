'use client'

import SectionState from '@/components/shared/SectionState'

/**
 * Read-only table of ponto (TimeEntry) events. The backend serializer
 * (TimeEntrySerializer, fields="__all__") returns only the raw `employee`
 * FK id — no denormalized name — so this list resolves display names from
 * the `employees` list fetched by the page, falling back to the raw id.
 */

export interface TimeEntryRow {
  id: string
  employee: string
  employee_name?: string
  event_type: 'in' | 'out'
  event_type_display?: string
  occurred_at: string
  source: 'web' | 'mobile' | 'device'
  source_display?: string
  recorded_by: string
  recorded_by_name?: string
  created_at: string
}

export interface TimeEntryEmployeeOption {
  id: string
  full_name: string
}

export interface TimeEntryListProps {
  entries: TimeEntryRow[]
  employees: TimeEntryEmployeeOption[]
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  in: 'Entrada',
  out: 'Saída',
}

const SOURCE_LABELS: Record<string, string> = {
  web: 'Web',
  mobile: 'Mobile',
  device: 'Relógio',
}

function resolveEmployeeName(
  entry: TimeEntryRow,
  employees: TimeEntryEmployeeOption[]
): string {
  if (entry.employee_name) return entry.employee_name
  const match = employees.find((e) => e.id === entry.employee)
  return match?.full_name ?? entry.employee ?? '—'
}

function formatDateTime(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return `${d.toLocaleDateString('pt-BR')} ${d.toLocaleTimeString('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
    })}`
  } catch {
    return dateStr
  }
}

export default function TimeEntryList({ entries, employees }: TimeEntryListProps) {
  if (entries.length === 0) {
    return (
      <SectionState
        title="Nenhuma marcação de ponto encontrada."
        detail="Use o botão Registrar marcação para lançar entradas e saídas da equipe."
      />
    )
  }

  return (
    <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-slate-100 bg-neu-panel">
            {['Funcionário', 'Tipo', 'Data/Hora', 'Origem', 'Registrado por'].map((h) => (
              <th
                key={h}
                className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {entries.map((entry) => (
            <tr key={entry.id} className="hover:bg-neu-panelAlt transition-colors">
              <td className="px-4 py-3 font-medium text-neu-ink">
                {resolveEmployeeName(entry, employees)}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">
                {entry.event_type_display ?? EVENT_TYPE_LABELS[entry.event_type] ?? entry.event_type}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft whitespace-nowrap">
                {formatDateTime(entry.occurred_at)}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">
                {entry.source_display ?? SOURCE_LABELS[entry.source] ?? entry.source}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">
                {entry.recorded_by_name ?? entry.recorded_by ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
