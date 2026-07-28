'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import AssignmentList from '@/components/hr/AssignmentList'
import type {
  Assignment,
  AssignmentEmployeeOption,
  AssignmentUnitOption,
  AssignmentPositionOption,
} from '@/components/hr/AssignmentList'
import AssignmentFormModal from '@/components/hr/AssignmentFormModal'

function normalizeList<T>(data: T[] | { results: T[] } | undefined | null): T[] {
  if (!data) return []
  return Array.isArray(data) ? data : (data as { results: T[] }).results ?? []
}

export default function LotacoesPage() {
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [employees, setEmployees] = useState<AssignmentEmployeeOption[]>([])
  const [units, setUnits] = useState<AssignmentUnitOption[]>([])
  const [positions, setPositions] = useState<AssignmentPositionOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [assignmentsData, employeesData, unitsData, positionsData] = await Promise.all([
        apiFetch<Assignment[] | { results: Assignment[] }>('/api/v1/hr/assignments/'),
        apiFetch<AssignmentEmployeeOption[] | { results: AssignmentEmployeeOption[] }>(
          '/api/v1/hr/employees/'
        ),
        apiFetch<AssignmentUnitOption[] | { results: AssignmentUnitOption[] }>(
          '/api/v1/organization/units/'
        ),
        apiFetch<AssignmentPositionOption[] | { results: AssignmentPositionOption[] }>(
          '/api/v1/hr/positions/'
        ),
      ])
      setAssignments(normalizeList(assignmentsData))
      setEmployees(normalizeList(employeesData))
      setUnits(normalizeList(unitsData))
      setPositions(normalizeList(positionsData))
    } catch {
      setError('Erro ao carregar lotações.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  function handleCreated() {
    setModalOpen(false)
    setSuccessMessage('Lotação criada ✓')
    setTimeout(() => setSuccessMessage(null), 4000)
    loadAll()
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Lotações</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Gerencie a lotação (unidade e cargo) dos funcionários. Cada funcionário tem no
            máximo uma lotação ativa por vez — criar uma nova lotação encerra
            automaticamente a anterior.
          </p>
        </div>
        <button
          onClick={() => setModalOpen(true)}
          className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
        >
          + Nova Lotação
        </button>
      </div>

      {successMessage && (
        <SectionState title={successMessage} detail="Operação concluída." tone="success" />
      )}

      {error && (
        <SectionState
          title="Erro ao carregar lotações."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && assignments.length === 0 && (
        <SectionState
          title="Nenhuma lotação cadastrada ainda."
          detail="Crie a primeira lotação para vincular um funcionário a uma unidade."
          action={
            <button
              onClick={() => setModalOpen(true)}
              className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
            >
              + Nova Lotação
            </button>
          }
        />
      )}

      {!loading && !error && assignments.length > 0 && (
        <AssignmentList
          assignments={assignments}
          employees={employees}
          units={units}
          positions={positions}
        />
      )}

      <AssignmentFormModal
        open={modalOpen}
        employees={employees}
        units={units}
        positions={positions}
        onClose={() => setModalOpen(false)}
        onSuccess={handleCreated}
      />
    </PageShell>
  )
}
