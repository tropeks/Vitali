'use client'

import type { Dependent } from '@/app/(dashboard)/rh/dependentes/page'
import type { Employee } from '@/app/(dashboard)/rh/funcionarios/page'

// ─── Constants ────────────────────────────────────────────────────────────────

const RELATIONSHIP_LABELS: Record<string, string> = {
  spouse: 'Cônjuge/companheiro(a)',
  child: 'Filho(a)',
  parent: 'Pai/Mãe',
  other: 'Outro',
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DependentListProps {
  dependents: Dependent[]
  employees: Employee[]
  onEdit: (dependent: Dependent) => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString('pt-BR')
  } catch {
    return dateStr
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function DependentList({ dependents, employees, onEdit }: DependentListProps) {
  const employeeName = (id: string): string =>
    employees.find((e) => e.id === id)?.full_name ?? '—'

  return (
    <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-slate-100 bg-neu-panel">
            {['Nome', 'Funcionário', 'Parentesco', 'Nascimento', 'CPF', 'IR', 'Ações'].map(
              (h) => (
                <th
                  key={h}
                  className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
                >
                  {h}
                </th>
              )
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {dependents.map((dep) => (
            <tr key={dep.id} className="hover:bg-neu-panelAlt transition-colors">
              <td className="px-4 py-3 font-medium text-neu-ink">{dep.full_name}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{employeeName(dep.employee)}</td>
              <td className="px-4 py-3 text-neu-inkSoft">
                {RELATIONSHIP_LABELS[dep.relationship] ?? dep.relationship}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">{formatDate(dep.birth_date)}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{dep.cpf || '—'}</td>
              <td className="px-4 py-3 text-neu-inkSoft">
                {dep.is_income_tax_dependent ? 'Sim' : 'Não'}
              </td>
              <td className="px-4 py-3">
                <button
                  onClick={() => onEdit(dep)}
                  className="text-neu-brand hover:underline text-xs font-semibold"
                >
                  Editar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
