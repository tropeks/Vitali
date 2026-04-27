'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import AddEmployeeModal from '@/components/hr/AddEmployeeModal'
import EmployeeEditModal from '@/components/hr/EmployeeEditModal'
import DeactivateConfirmModal from '@/components/hr/DeactivateConfirmModal'

// ─── Types ────────────────────────────────────────────────────────────────────

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

// ─── Label maps ───────────────────────────────────────────────────────────────

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

const STATUS_CONFIG: Record<
  Employee['employment_status'],
  { label: string; className: string }
> = {
  active: {
    label: 'Ativo',
    className: 'bg-green-100 text-green-700 px-2 py-0.5 rounded-full text-xs',
  },
  on_leave: {
    label: 'Afastado',
    className: 'bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full text-xs',
  },
  terminated: {
    label: 'Desligado',
    className: 'bg-red-100 text-red-700 px-2 py-0.5 rounded-full text-xs',
  },
}

// ─── Component ────────────────────────────────────────────────────────────────

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
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Funcionários</h1>
          <p className="text-sm text-slate-500 mt-0.5">Gerencie a equipe da sua clínica.</p>
        </div>
        <button
          onClick={() => setAddModalOpen(true)}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          + Adicionar Funcionário
        </button>
      </div>

      {/* Success toasts */}
      {successMessages.length > 0 && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-lg space-y-1">
          {successMessages.map((msg, i) => (
            <p key={i} className="text-sm text-green-700 font-medium">
              {msg}
            </p>
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <p className="text-sm text-slate-500">Carregando...</p>
      )}

      {/* Empty state */}
      {!loading && !error && employees.length === 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm py-16 flex flex-col items-center gap-4">
          <p className="text-slate-500 text-sm">Nenhum funcionário cadastrado ainda.</p>
          <button
            onClick={() => setAddModalOpen(true)}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            + Adicionar Funcionário
          </button>
        </div>
      )}

      {/* Table */}
      {!loading && !error && employees.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Nome', 'Email', 'Função', 'Vínculo', 'Status', 'Admissão', 'Ações'].map(
                  (h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 font-medium text-slate-600"
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {employees.map((emp) => {
                const status = STATUS_CONFIG[emp.employment_status] ?? STATUS_CONFIG.active
                return (
                  <tr
                    key={emp.id}
                    className="border-b border-slate-100 hover:bg-slate-50"
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{emp.full_name}</td>
                    <td className="px-4 py-3 text-slate-600">{emp.email}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {ROLE_LABELS[emp.role] ?? emp.role ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {CONTRACT_LABELS[emp.contract_type] ?? emp.contract_type ?? '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={status.className}>{status.label}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{formatDate(emp.hire_date)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setEditingEmployee(emp)}
                        className="text-blue-600 hover:text-blue-700 text-sm font-medium"
                      >
                        Editar
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Modals */}
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
    </div>
  )
}
