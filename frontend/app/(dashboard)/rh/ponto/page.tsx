'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import TimeEntryList from '@/components/hr/TimeEntryList'
import TimeEntryForm from '@/components/hr/TimeEntryForm'

export interface TimeEntry {
  id: string
  employee: string
  employee_name?: string
  event_type: 'in' | 'out'
  event_type_display?: string
  occurred_at: string
  source: 'web' | 'mobile' | 'device'
  source_display?: string
  external_id?: string
  correction_of?: string | null
  reason?: string
  recorded_by: string
  recorded_by_name?: string
  created_at: string
}

export interface EmployeeOption {
  id: string
  full_name: string
}

type Listish<T> = T[] | { results: T[] }

function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : (data as { results: T[] }).results ?? []
}

export default function PontoPage() {
  const [entries, setEntries] = useState<TimeEntry[]>([])
  const [employees, setEmployees] = useState<EmployeeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [employeeFilter, setEmployeeFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const query = employeeFilter ? `?employee=${employeeFilter}` : ''
      const [list, emps] = await Promise.all([
        apiFetch<Listish<TimeEntry>>(`/api/v1/hr/time-entries/${query}`),
        apiFetch<Listish<EmployeeOption>>('/api/v1/hr/employees/').catch(
          () => [] as EmployeeOption[]
        ),
      ])
      setEntries(unwrap(list))
      setEmployees(unwrap(emps))
    } catch {
      setError('Erro ao carregar marcações de ponto.')
    } finally {
      setLoading(false)
    }
  }, [employeeFilter])

  useEffect(() => {
    load()
  }, [load])

  function flashSuccess(msg: string) {
    setSuccessMessage(msg)
    setTimeout(() => setSuccessMessage(null), 4000)
  }

  const filteredEntries = entries.filter((entry) => {
    if (!dateFrom && !dateTo) return true
    const day = entry.occurred_at.slice(0, 10)
    if (dateFrom && day < dateFrom) return false
    if (dateTo && day > dateTo) return false
    return true
  })

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Ponto</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Registro de marcações de jornada (entrada/saída) da equipe.
          </p>
        </div>
        <button
          onClick={() => setFormOpen(true)}
          className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
        >
          + Registrar marcação
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3 bg-neu-panel rounded-lg border border-slate-200 p-4">
        <div>
          <label htmlFor="ponto_filter_employee" className="block text-xs font-medium text-slate-700 mb-1">
            Filtrar por funcionário
          </label>
          <select
            id="ponto_filter_employee"
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
        <div>
          <label htmlFor="ponto_filter_from" className="block text-xs font-medium text-slate-700 mb-1">
            De
          </label>
          <input
            id="ponto_filter_from"
            type="date"
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="ponto_filter_to" className="block text-xs font-medium text-slate-700 mb-1">
            Até
          </label>
          <input
            id="ponto_filter_to"
            type="date"
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {successMessage && (
        <SectionState title={successMessage} detail="Operação concluída." tone="success" />
      )}

      {error && (
        <SectionState
          title="Erro ao carregar marcações de ponto."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && <TimeEntryList entries={filteredEntries} employees={employees} />}

      <TimeEntryForm
        open={formOpen}
        employees={employees}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          flashSuccess('Marcação registrada ✓')
          load()
        }}
      />
    </PageShell>
  )
}
