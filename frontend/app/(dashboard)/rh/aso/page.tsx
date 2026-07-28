'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import AsoList from '@/components/hr/AsoList'
import AsoForm from '@/components/hr/AsoForm'

export interface OccupationalHealthExam {
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
  certificate_reference?: string
  restrictions?: string
  recorded_by: string
  recorded_by_name?: string
  created_at: string
  updated_at: string
}

export interface EmployeeOption {
  id: string
  full_name: string
}

type Listish<T> = T[] | { results: T[] }

function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : (data as { results: T[] }).results ?? []
}

export default function AsoPage() {
  const [exams, setExams] = useState<OccupationalHealthExam[]>([])
  const [employees, setEmployees] = useState<EmployeeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [employeeFilter, setEmployeeFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, emps] = await Promise.all([
        apiFetch<Listish<OccupationalHealthExam>>('/api/v1/hr/occupational-health-exams/'),
        apiFetch<Listish<EmployeeOption>>('/api/v1/hr/employees/').catch(
          () => [] as EmployeeOption[]
        ),
      ])
      setExams(unwrap(list))
      setEmployees(unwrap(emps))
    } catch {
      setError('Erro ao carregar ASOs.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function flashSuccess(msg: string) {
    setSuccessMessage(msg)
    setTimeout(() => setSuccessMessage(null), 4000)
  }

  // The backend viewset has no server-side employee filter for exams, so
  // filtering happens client-side over the already-fetched list.
  const filteredExams = employeeFilter
    ? exams.filter((exam) => exam.employee === employeeFilter)
    : exams

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">ASO</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Exames de saúde ocupacional da equipe — sem achados clínicos armazenados em RH.
          </p>
        </div>
        <button
          onClick={() => setFormOpen(true)}
          className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
        >
          + Novo ASO
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3 bg-neu-panel rounded-lg border border-slate-200 p-4">
        <div>
          <label htmlFor="aso_filter_employee" className="block text-xs font-medium text-slate-700 mb-1">
            Filtrar por funcionário
          </label>
          <select
            id="aso_filter_employee"
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={employeeFilter}
            onChange={(e) => setEmployeeFilter(e.target.value)}
          >
            <option value="">Todos</option>
            {employees.map((emp) => (
              <option key={emp.id} value={emp.id}>
                {emp.full_name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {successMessage && (
        <SectionState title={successMessage} detail="Operação concluída." tone="success" />
      )}

      {error && (
        <SectionState
          title="Erro ao carregar ASOs."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && <AsoList exams={filteredExams} employees={employees} />}

      <AsoForm
        open={formOpen}
        employees={employees}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          flashSuccess('ASO registrado ✓')
          load()
        }}
      />
    </PageShell>
  )
}
