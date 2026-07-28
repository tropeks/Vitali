'use client'

import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { formatCPF } from '@/lib/formatters'
import type { Dependent, DependentRelationship } from '@/app/(dashboard)/rh/dependentes/page'
import type { Employee } from '@/app/(dashboard)/rh/funcionarios/page'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DependentFormModalProps {
  open: boolean
  dependent: Dependent | null
  employees: Employee[]
  onClose: () => void
  onSuccess: () => void
}

// ─── Constants ────────────────────────────────────────────────────────────────

const RELATIONSHIP_OPTIONS: { value: DependentRelationship; label: string }[] = [
  { value: 'spouse', label: 'Cônjuge/companheiro(a)' },
  { value: 'child', label: 'Filho(a)' },
  { value: 'parent', label: 'Pai/Mãe' },
  { value: 'other', label: 'Outro' },
]

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
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

export default function DependentFormModal({
  open,
  dependent,
  employees,
  onClose,
  onSuccess,
}: DependentFormModalProps) {
  const [employeeId, setEmployeeId] = useState('')
  const [fullName, setFullName] = useState('')
  const [relationship, setRelationship] = useState<DependentRelationship>('child')
  const [birthDate, setBirthDate] = useState('')
  const [cpf, setCpf] = useState('')
  const [isIncomeTaxDependent, setIsIncomeTaxDependent] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isEditing = dependent !== null

  // Sync form with incoming dependent (or reset for create) whenever the modal opens
  useEffect(() => {
    if (open) {
      setEmployeeId(dependent?.employee ?? '')
      setFullName(dependent?.full_name ?? '')
      setRelationship(dependent?.relationship ?? 'child')
      setBirthDate(dependent?.birth_date ?? '')
      setCpf(dependent?.cpf ?? '')
      setIsIncomeTaxDependent(dependent?.is_income_tax_dependent ?? false)
      setError(null)
    }
  }, [open, dependent])

  if (!open) return null

  const canSubmit = employeeId !== '' && fullName.trim().length > 0 && !saving

  async function handleSubmit() {
    setSaving(true)
    setError(null)

    const payload = {
      employee: employeeId,
      full_name: fullName.trim(),
      relationship,
      birth_date: birthDate || null,
      cpf: cpf.replace(/\D/g, ''),
      is_income_tax_dependent: isIncomeTaxDependent,
    }

    try {
      if (isEditing && dependent) {
        await apiFetch(`/api/v1/hr/dependents/${dependent.id}/`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })
      } else {
        await apiFetch('/api/v1/hr/dependents/', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      }
      onSuccess()
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-lg w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-slate-900">
            {isEditing ? 'Editar Dependente' : 'Novo Dependente'}
          </h2>
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
          <div>
            <label htmlFor="dependent-employee" className={LABEL_CLASS}>
              Funcionário <span className="text-red-500">*</span>
            </label>
            <select
              id="dependent-employee"
              className={SELECT_CLASS}
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
            >
              <option value="">Selecione um funcionário...</option>
              {employees.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.full_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="dependent-full-name" className={LABEL_CLASS}>
              Nome do dependente <span className="text-red-500">*</span>
            </label>
            <input
              id="dependent-full-name"
              type="text"
              className={INPUT_CLASS}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Ex.: Ana Silva"
            />
          </div>

          <div>
            <label htmlFor="dependent-relationship" className={LABEL_CLASS}>
              Parentesco <span className="text-red-500">*</span>
            </label>
            <select
              id="dependent-relationship"
              className={SELECT_CLASS}
              value={relationship}
              onChange={(e) => setRelationship(e.target.value as DependentRelationship)}
            >
              {RELATIONSHIP_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="dependent-birth-date" className={LABEL_CLASS}>
              Data de nascimento <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <input
              id="dependent-birth-date"
              type="date"
              className={INPUT_CLASS}
              value={birthDate}
              onChange={(e) => setBirthDate(e.target.value)}
            />
          </div>

          <div>
            <label htmlFor="dependent-cpf" className={LABEL_CLASS}>
              CPF <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <input
              id="dependent-cpf"
              type="text"
              inputMode="numeric"
              className={INPUT_CLASS}
              value={formatCPF(cpf)}
              onChange={(e) => setCpf(e.target.value.replace(/\D/g, ''))}
              placeholder="000.000.000-00"
              maxLength={14}
            />
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isIncomeTaxDependent}
              onChange={(e) => setIsIncomeTaxDependent(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-slate-700">Dependente para IR</span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-slate-100">
          <button
            onClick={onClose}
            disabled={saving}
            className="border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? 'Salvando...' : isEditing ? 'Salvar' : 'Cadastrar Dependente'}
          </button>
        </div>
      </div>
    </div>
  )
}
