'use client'

import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import type { Employee } from '@/app/(dashboard)/rh/funcionarios/page'
import DeactivateConfirmModal from './DeactivateConfirmModal'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface EmployeeEditModalProps {
  open: boolean
  employee: Employee | null
  onClose: () => void
  onUpdate: () => void
  onDeactivate: (employee: Employee) => void
}

type EmployeeRole = 'admin' | 'medico' | 'enfermeiro' | 'recepcao' | 'faturista' | 'farmaceutico' | 'dentista'
type ContractType = 'clt' | 'pj' | 'autonomo' | 'estagiario'
type EmploymentStatus = 'active' | 'on_leave' | 'terminated'

// ─── Constants ────────────────────────────────────────────────────────────────

const ROLE_LABELS: Record<EmployeeRole, string> = {
  admin: 'Admin',
  medico: 'Médico',
  enfermeiro: 'Enfermeiro',
  recepcao: 'Recepção',
  faturista: 'Faturista',
  farmaceutico: 'Farmacêutico',
  dentista: 'Dentista',
}

const CONTRACT_LABELS: Record<ContractType, string> = {
  clt: 'CLT',
  pj: 'PJ',
  autonomo: 'Autônomo',
  estagiario: 'Estagiário',
}

const STATUS_LABELS: Record<EmploymentStatus, string> = {
  active: 'Ativo',
  on_leave: 'Afastado',
  terminated: 'Desligado',
}

// ─── Shared input classes ─────────────────────────────────────────────────────

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const INPUT_READONLY_CLASS =
  'w-full border border-slate-100 rounded-lg px-3 py-2 text-sm bg-slate-50 text-slate-500 cursor-not-allowed'
const SELECT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white'
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

// ─── Field error extraction ───────────────────────────────────────────────────

function extractError(err: any): string {
  if (typeof err === 'string') return err
  if (err?.detail) return String(err.detail)
  const firstVal = Object.values(err ?? {})[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao salvar. Tente novamente.'
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function EmployeeEditModal({
  open,
  employee,
  onClose,
  onUpdate,
  onDeactivate,
}: EmployeeEditModalProps) {
  const [role, setRole] = useState<EmployeeRole>('recepcao')
  const [contractType, setContractType] = useState<ContractType>('clt')
  const [employmentStatus, setEmploymentStatus] = useState<EmploymentStatus>('active')
  const [phone, setPhone] = useState('')
  const [hireDate, setHireDate] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deactivateOpen, setDeactivateOpen] = useState(false)

  // Sync form with incoming employee
  useEffect(() => {
    if (employee) {
      setRole((employee.role as EmployeeRole) ?? 'recepcao')
      setContractType((employee.contract_type as ContractType) ?? 'clt')
      setEmploymentStatus((employee.employment_status as EmploymentStatus) ?? 'active')
      setPhone(employee.phone ?? '')
      setHireDate(employee.hire_date ?? '')
      setError(null)
    }
  }, [employee])

  if (!open || !employee) return null

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      await apiFetch(`/api/v1/hr/employees/${employee.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({
          role,
          contract_type: contractType,
          employment_status: employmentStatus,
          phone: phone || undefined,
          hire_date: hireDate || undefined,
        }),
      })
      onUpdate()
      onClose()
    } catch (err) {
      if (err instanceof ApiError) {
        setError(extractError(err.body))
      } else {
        setError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  function handleDeactivateClick() {
    onDeactivate(employee!)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-lg w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Editar Funcionário</h2>
            <p className="text-xs text-slate-500 mt-0.5">{employee.full_name}</p>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            className="text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {/* Form */}
        <div className="flex-1 overflow-y-auto space-y-4">
          {/* Read-only fields */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={LABEL_CLASS}>Nome completo</label>
              <input
                type="text"
                readOnly
                value={employee.full_name}
                className={INPUT_READONLY_CLASS}
              />
            </div>
            <div>
              <label className={LABEL_CLASS}>E-mail</label>
              <input
                type="email"
                readOnly
                value={employee.email}
                className={INPUT_READONLY_CLASS}
              />
            </div>
          </div>

          {employee.cpf && (
            <div>
              <label className={LABEL_CLASS}>CPF</label>
              <input
                type="text"
                readOnly
                value={employee.cpf}
                className={INPUT_READONLY_CLASS}
              />
            </div>
          )}

          {/* Editable fields */}
          <div>
            <label htmlFor="edit-role" className={LABEL_CLASS}>
              Função
            </label>
            <select
              id="edit-role"
              className={SELECT_CLASS}
              value={role}
              onChange={(e) => setRole(e.target.value as EmployeeRole)}
            >
              {(Object.keys(ROLE_LABELS) as EmployeeRole[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="edit-contract-type" className={LABEL_CLASS}>
              Tipo de contrato
            </label>
            <select
              id="edit-contract-type"
              className={SELECT_CLASS}
              value={contractType}
              onChange={(e) => setContractType(e.target.value as ContractType)}
            >
              {(Object.keys(CONTRACT_LABELS) as ContractType[]).map((c) => (
                <option key={c} value={c}>
                  {CONTRACT_LABELS[c]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="edit-employment-status" className={LABEL_CLASS}>
              Status
            </label>
            <select
              id="edit-employment-status"
              className={SELECT_CLASS}
              value={employmentStatus}
              onChange={(e) => setEmploymentStatus(e.target.value as EmploymentStatus)}
            >
              {(Object.keys(STATUS_LABELS) as EmploymentStatus[]).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="edit-phone" className={LABEL_CLASS}>
              Telefone
            </label>
            <input
              id="edit-phone"
              type="tel"
              className={INPUT_CLASS}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+5511999999999"
            />
          </div>

          <div>
            <label htmlFor="edit-hire-date" className={LABEL_CLASS}>
              Data de admissão
            </label>
            <input
              id="edit-hire-date"
              type="date"
              className={INPUT_CLASS}
              value={hireDate}
              onChange={(e) => setHireDate(e.target.value)}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100">
          <button
            onClick={handleDeactivateClick}
            disabled={saving}
            className="text-red-600 border border-red-200 rounded-lg px-4 py-2 text-sm font-medium hover:bg-red-50 transition-colors disabled:opacity-50"
          >
            Desativar funcionário
          </button>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              disabled={saving}
              className="border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {saving ? 'Salvando...' : 'Salvar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
