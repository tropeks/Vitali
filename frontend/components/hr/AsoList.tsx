'use client'

import SectionState from '@/components/shared/SectionState'
import StatusBadge from '@/components/shared/StatusBadge'

/**
 * Read-only table of ASO / occupational health exams. The backend serializer
 * (OccupationalHealthExamSerializer, fields="__all__") returns only the raw
 * `employee` FK id — no denormalized name — so this list resolves display
 * names from the `employees` list fetched by the page, falling back to the
 * raw id. Expiry is highlighted when already vencido or due within 30 days.
 */

export interface AsoExamRow {
  id: string
  employee: string
  employee_name?: string
  exam_type: string
  exam_type_display?: string
  performed_on: string
  expires_on?: string | null
  result: 'fit' | 'unfit' | 'pending'
  result_display?: string
  provider_name: string
  recorded_by: string
  recorded_by_name?: string
  created_at: string
  updated_at: string
}

export interface AsoEmployeeOption {
  id: string
  full_name: string
}

export interface AsoListProps {
  exams: AsoExamRow[]
  employees: AsoEmployeeOption[]
  /** ISO date (YYYY-MM-DD) used to compute vencido/perto-do-vencimento. Defaults to today. */
  referenceDate?: string
}

const EXAM_TYPE_LABELS: Record<string, string> = {
  admission: 'Admissional',
  periodic: 'Periódico',
  return: 'Retorno ao trabalho',
  role_change: 'Mudança de risco',
  termination: 'Demissional',
}

const RESULT_META: Record<string, { label: string; badgeClass: string }> = {
  fit: { label: 'Apto', badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20' },
  unfit: { label: 'Inapto', badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20' },
  pending: {
    label: 'Pendente',
    badgeClass: 'bg-neu-warning/10 text-neu-warning border-neu-warning/20',
  },
}

const FALLBACK_META = {
  label: '—',
  badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
}

const NEAR_EXPIRY_DAYS = 30

function resolveEmployeeName(exam: AsoExamRow, employees: AsoEmployeeOption[]): string {
  if (exam.employee_name) return exam.employee_name
  const match = employees.find((e) => e.id === exam.employee)
  return match?.full_name ?? exam.employee ?? '—'
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString('pt-BR')
  } catch {
    return dateStr
  }
}

function expiryStatus(
  expiresOn: string | null | undefined,
  referenceDate: string
): 'expired' | 'near' | 'ok' | null {
  if (!expiresOn) return null
  const ref = new Date(referenceDate + 'T00:00:00')
  const exp = new Date(expiresOn + 'T00:00:00')
  const diffDays = Math.floor((exp.getTime() - ref.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return 'expired'
  if (diffDays <= NEAR_EXPIRY_DAYS) return 'near'
  return 'ok'
}

export default function AsoList({ exams, employees, referenceDate }: AsoListProps) {
  const today = referenceDate ?? new Date().toISOString().slice(0, 10)

  if (exams.length === 0) {
    return (
      <SectionState
        title="Nenhum ASO registrado ainda."
        detail="Use o botão Novo ASO para registrar um exame ocupacional da equipe."
      />
    )
  }

  return (
    <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-slate-100 bg-neu-panel">
            {['Funcionário', 'Tipo', 'Data', 'Aptidão', 'Vencimento'].map((h) => (
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
          {exams.map((exam) => {
            const status = expiryStatus(exam.expires_on, today)
            const meta = RESULT_META[exam.result] ?? FALLBACK_META
            return (
              <tr key={exam.id} className="hover:bg-neu-panelAlt transition-colors">
                <td className="px-4 py-3 font-medium text-neu-ink">
                  {resolveEmployeeName(exam, employees)}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  {exam.exam_type_display ?? EXAM_TYPE_LABELS[exam.exam_type] ?? exam.exam_type}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft whitespace-nowrap">
                  {formatDate(exam.performed_on)}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge meta={{ label: exam.result_display ?? meta.label, badgeClass: meta.badgeClass }} />
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <span
                    className={
                      status === 'expired'
                        ? 'text-neu-danger font-semibold'
                        : status === 'near'
                          ? 'text-neu-warning font-semibold'
                          : 'text-neu-inkSoft'
                    }
                  >
                    {formatDate(exam.expires_on)}
                  </span>
                  {status === 'expired' && (
                    <span className="ml-2 text-xs text-neu-danger">(vencido)</span>
                  )}
                  {status === 'near' && (
                    <span className="ml-2 text-xs text-neu-warning">(vence em breve)</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
