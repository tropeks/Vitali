'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState, StatusBadge } from '@/components/shared'
import { EMPLOYMENT_STATUS_META, resolveBadgeMeta } from '@/lib/operational-ui'
import AddEmployeeModal from '@/components/hr/AddEmployeeModal'
import EmployeeEditModal from '@/components/hr/EmployeeEditModal'
import DeactivateConfirmModal from '@/components/hr/DeactivateConfirmModal'

export interface Employee {
  id: string
  user: string
  full_name: string
  email: string
  role: string
  employment_status: 'active' | 'on_leave' | 'terminated'
  hire_date: string
  contract_type: string
  terminated_at: string | null
  created_at: string
  phone?: string
  cpf?: string
}

const ROLE_LABELS: Record<string, string> = {
  admin: 'Admin',
  medico: 'Médico',
  enfermeiro: 'Enfermeiro',
  recepcao: 'Recepção',
  faturista: 'Faturista',
  farmaceutico: 'Farmacêutico',
  dentista: 'Dentista',
}

const CONTRACT_LABELS: Record<string, string> = {
  clt: 'CLT',
  pj: 'PJ',
  autonomo: 'Autônomo',
  estagiario: 'Estagiário',
}

export default function FuncionariosPage() {
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [deactivatingEmployee, setDeactivatingEmployee] = useState<Employee | null>(null)
  const [successMessages, setSuccessMessages] = useState<string[]>([])

  const loadEmployees = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<Employee[] | { results: Employee[] }>(
        '/api/v1/hr/employees/'
      )
      setEmployees(Array.isArray(data) ? data : (data as { results: Employee[] }).results ?? [])
    } catch {
      setError('Erro ao carregar funcionários.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadEmployees()
  }, [loadEmployees])

  function showSuccessToast(msgs: string[]) {
    setSuccessMessages(msgs)
    setTimeout(() => setSuccessMessages([]), 4000)
  }

  function handleDeactivated(msgs: string[]) {
    setDeactivatingEmployee(null)
    setEditingEmployee(null)
    showSuccessToast(msgs)
    loadEmployees()
  }

  function formatDate(dateStr: string | null | undefined): string {
    if (!dateStr) return '—'
    try {
      return new Date(dateStr + 'T00:00:00').toLocaleDateString('pt-BR')
    } catch {
      return dateStr
    }
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Funcionários</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">Gerencie a equipe da sua clínica.</p>
        </div>
        <button
          onClick={() => setAddModalOpen(true)}
          className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
        >
          + Adicionar Funcionário
        </button>
      </div>

      {successMessages.length > 0 && (
        <SectionState
          title={successMessages[0]}
          detail={successMessages.slice(1).join(' · ') || 'Operação concluída.'}
          tone="success"
        />
      )}

      {error && (
        <SectionState
          title="Erro ao carregar funcionários."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && employees.length === 0 && (
        <SectionState
          title="Nenhum funcionário cadastrado ainda."
          detail="Adicione o primeiro funcionário para começar a operar a equipe."
          action={
            <button
              onClick={() => setAddModalOpen(true)}
              className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
            >
              + Adicionar Funcionário
            </button>
          }
        />
      )}

      {!loading && !error && employees.length > 0 && (
        <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-slate-100 bg-neu-panel">
                {['Nome', 'Email', 'Função', 'Vínculo', 'Status', 'Admissão', 'Ações'].map(
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
              {employees.map((emp) => (
                <tr key={emp.id} className="hover:bg-neu-panelAlt transition-colors">
                  <td className="px-4 py-3 font-medium text-neu-ink">{emp.full_name}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">{emp.email}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {ROLE_LABELS[emp.role] ?? emp.role ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {CONTRACT_LABELS[emp.contract_type] ?? emp.contract_type ?? '—'}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge
                      meta={resolveBadgeMeta(EMPLOYMENT_STATUS_META, emp.employment_status)}
                    />
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">{formatDate(emp.hire_date)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setEditingEmployee(emp)}
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
      )}

      <AddEmployeeModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        onSuccess={() => {
          setAddModalOpen(false)
          loadEmployees()
        }}
      />

      <EmployeeEditModal
        open={editingEmployee !== null}
        employee={editingEmployee}
        onClose={() => setEditingEmployee(null)}
        onUpdate={loadEmployees}
        onDeactivate={(emp) => {
          setDeactivatingEmployee(emp)
        }}
      />

      <DeactivateConfirmModal
        open={deactivatingEmployee !== null}
        employee={deactivatingEmployee}
        onClose={() => setDeactivatingEmployee(null)}
        onDeactivated={handleDeactivated}
      />
    </PageShell>
  )
}
