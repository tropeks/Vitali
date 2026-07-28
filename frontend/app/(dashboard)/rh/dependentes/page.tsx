'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import type { Employee } from '@/app/(dashboard)/rh/funcionarios/page'
import DependentList from '@/components/hr/DependentList'
import DependentFormModal from '@/components/hr/DependentFormModal'

export type DependentRelationship = 'spouse' | 'child' | 'parent' | 'other'

export interface Dependent {
  id: string
  employee: string
  full_name: string
  relationship: DependentRelationship
  birth_date: string | null
  cpf: string
  is_income_tax_dependent: boolean
  created_at: string
}

const PRIMARY_BTN =
  'px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all'

export default function DependentesPage() {
  const [employees, setEmployees] = useState<Employee[]>([])
  const [dependents, setDependents] = useState<Dependent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [employeeFilter, setEmployeeFilter] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editingDependent, setEditingDependent] = useState<Dependent | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)

    // Employee list feeds the filter dropdown and the create/edit form's
    // employee picker, and resolves employee names in the table. It is
    // non-fatal if it fails: dependents can still load, they just show raw
    // employee ids until the employee list is available.
    try {
      const empData = await apiFetch<Employee[] | { results: Employee[] }>(
        '/api/v1/hr/employees/'
      )
      setEmployees(Array.isArray(empData) ? empData : (empData as { results: Employee[] }).results ?? [])
    } catch {
      // ignore — degrade gracefully
    }

    try {
      const depData = await apiFetch<Dependent[] | { results: Dependent[] }>(
        '/api/v1/hr/dependents/'
      )
      setDependents(
        Array.isArray(depData) ? depData : (depData as { results: Dependent[] }).results ?? []
      )
    } catch {
      setError('Erro ao carregar dependentes.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  function openCreate() {
    setEditingDependent(null)
    setFormOpen(true)
  }

  function openEdit(dependent: Dependent) {
    setEditingDependent(dependent)
    setFormOpen(true)
  }

  const filteredDependents = employeeFilter
    ? dependents.filter((d) => d.employee === employeeFilter)
    : dependents

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Dependentes</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Dependentes cadastrados para benefícios dos funcionários.
          </p>
        </div>
        <button onClick={openCreate} className={PRIMARY_BTN}>
          + Novo Dependente
        </button>
      </div>

      <div className="flex items-center gap-2">
        <label htmlFor="employee-filter" className="text-xs font-medium text-neu-inkMuted">
          Filtrar por funcionário
        </label>
        <select
          id="employee-filter"
          value={employeeFilter}
          onChange={(e) => setEmployeeFilter(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">Todos os funcionários</option>
          {employees.map((emp) => (
            <option key={emp.id} value={emp.id}>
              {emp.full_name}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar dependentes."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && filteredDependents.length === 0 && (
        <SectionState
          title="Nenhum dependente cadastrado ainda."
          detail="Cadastre o primeiro dependente para associá-lo a um funcionário."
          action={
            <button onClick={openCreate} className={PRIMARY_BTN}>
              + Novo Dependente
            </button>
          }
        />
      )}

      {!loading && !error && filteredDependents.length > 0 && (
        <DependentList dependents={filteredDependents} employees={employees} onEdit={openEdit} />
      )}

      <DependentFormModal
        open={formOpen}
        dependent={editingDependent}
        employees={employees}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          loadData()
        }}
      />
    </PageShell>
  )
}
