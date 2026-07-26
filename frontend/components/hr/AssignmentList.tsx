'use client'

/**
 * Presentational table for employee assignments ("lotações").
 *
 * The EmployeeAssignment API returns FK fields as bare ids (serializer
 * fields="__all__" — no nested representation), so this component resolves
 * employee/unit/position ids to display labels using the option lists
 * fetched by the parent page.
 */

export interface Assignment {
  id: string
  employee: string
  unit: string
  cost_center: string | null
  position: string | null
  role: string
  start_date: string
  end_date: string | null
  active: boolean
  created_at: string
  updated_at: string
}

export interface AssignmentEmployeeOption {
  id: string
  full_name: string
}

export interface AssignmentUnitOption {
  id: string
  name: string
}

export interface AssignmentPositionOption {
  id: string
  title: string
}

interface AssignmentListProps {
  assignments: Assignment[]
  employees: AssignmentEmployeeOption[]
  units: AssignmentUnitOption[]
  positions: AssignmentPositionOption[]
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString('pt-BR')
  } catch {
    return dateStr
  }
}

export default function AssignmentList({
  assignments,
  employees,
  units,
  positions,
}: AssignmentListProps) {
  const employeeName = (id: string) => employees.find((e) => e.id === id)?.full_name ?? id
  const unitName = (id: string) => units.find((u) => u.id === id)?.name ?? id
  const positionTitle = (id: string | null) =>
    id ? positions.find((p) => p.id === id)?.title ?? id : '—'

  return (
    <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-slate-100 bg-neu-panel">
            {['Funcionário', 'Unidade', 'Cargo', 'Status', 'Início', 'Fim'].map((h) => (
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
          {assignments.map((a) => (
            <tr key={a.id} className="hover:bg-neu-panelAlt transition-colors">
              <td className="px-4 py-3 font-medium text-neu-ink">{employeeName(a.employee)}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{unitName(a.unit)}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{positionTitle(a.position)}</td>
              <td className="px-4 py-3">
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                    a.active ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {a.active ? 'Ativa' : 'Encerrada'}
                </span>
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">{formatDate(a.start_date)}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{formatDate(a.end_date)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
