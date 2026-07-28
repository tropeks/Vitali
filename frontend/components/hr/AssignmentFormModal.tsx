'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import type {
  Assignment,
  AssignmentEmployeeOption,
  AssignmentUnitOption,
  AssignmentPositionOption,
} from './AssignmentList'

export interface AssignmentFormModalProps {
  open: boolean
  employees: AssignmentEmployeeOption[]
  units: AssignmentUnitOption[]
  positions: AssignmentPositionOption[]
  onClose: () => void
  onSuccess: (assignment: Assignment) => void
}

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-slate-400'
const SELECT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white'
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'
const PRIMARY_BTN =
  'bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
const SECONDARY_BTN =
  'border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors'

function extractFieldErrors(body: any): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [key, val] of Object.entries(body)) {
    if (Array.isArray(val) && val.length > 0) {
      errors[key] = String(val[0])
    } else if (typeof val === 'string') {
      errors[key] = val
    }
  }
  return errors
}

interface Form {
  employee: string
  unit: string
  position: string
  role: string
  start_date: string
}

const INITIAL_FORM: Form = {
  employee: '',
  unit: '',
  position: '',
  role: '',
  start_date: '',
}

/**
 * Create form for a new employee assignment ("lotação").
 *
 * IMPORTANT: `active` and `end_date` (plus `id`/`created_at`/`updated_at`) are
 * read-only / server-managed — AssignmentService.assign closes the employee's
 * current active assignment and opens this one atomically. The client must
 * never send those fields; only `employee`, `unit`, `start_date` (required)
 * and `position`/`role` (optional) are POSTed.
 */
export default function AssignmentFormModal({
  open,
  employees,
  units,
  positions,
  onClose,
  onSuccess,
}: AssignmentFormModalProps) {
  const [form, setForm] = useState<Form>(INITIAL_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')

  if (!open) return null

  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const handleClose = () => {
    setForm(INITIAL_FORM)
    setFieldErrors({})
    setGlobalError('')
    onClose()
  }

  const canSubmit =
    form.employee !== '' && form.unit !== '' && form.start_date !== '' && !submitting

  const handleSubmit = async () => {
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const payload: Record<string, unknown> = {
      employee: form.employee,
      unit: form.unit,
      start_date: form.start_date,
      position: form.position || undefined,
      role: form.role.trim() || undefined,
    }

    try {
      const assignment = await apiFetch<Assignment>('/api/v1/hr/assignments/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess(assignment)
      handleClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const errors = extractFieldErrors(err.body)
        setFieldErrors(errors)
        setGlobalError(Object.values(errors)[0] ?? 'Erro ao criar lotação.')
      } else {
        setGlobalError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const FieldError = ({ field }: { field: string }) =>
    fieldErrors[field] ? <p className="text-xs text-red-600 mt-1">{fieldErrors[field]}</p> : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Nova Lotação</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Criar uma nova lotação encerra automaticamente a lotação ativa atual do
              funcionário — apenas uma lotação ativa é permitida por vez.
            </p>
          </div>
          <button
            onClick={handleClose}
            disabled={submitting}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
          >
            <X size={20} />
          </button>
        </div>

        {globalError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">{globalError}</p>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label htmlFor="employee" className={LABEL_CLASS}>
              Funcionário <span className="text-red-500">*</span>
            </label>
            <select
              id="employee"
              className={SELECT_CLASS}
              value={form.employee}
              onChange={(e) => set('employee', e.target.value)}
            >
              <option value="">Selecione...</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.full_name}
                </option>
              ))}
            </select>
            <FieldError field="employee" />
          </div>

          <div>
            <label htmlFor="unit" className={LABEL_CLASS}>
              Unidade <span className="text-red-500">*</span>
            </label>
            <select
              id="unit"
              className={SELECT_CLASS}
              value={form.unit}
              onChange={(e) => set('unit', e.target.value)}
            >
              <option value="">Selecione...</option>
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
            <FieldError field="unit" />
          </div>

          <div>
            <label htmlFor="position" className={LABEL_CLASS}>
              Cargo <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <select
              id="position"
              className={SELECT_CLASS}
              value={form.position}
              onChange={(e) => set('position', e.target.value)}
            >
              <option value="">Selecione...</option>
              {positions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
            <FieldError field="position" />
          </div>

          <div>
            <label htmlFor="role" className={LABEL_CLASS}>
              Função <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <input
              id="role"
              type="text"
              className={INPUT_CLASS}
              value={form.role}
              onChange={(e) => set('role', e.target.value)}
              placeholder="Ex.: Enfermeiro plantonista"
              maxLength={160}
            />
            <FieldError field="role" />
          </div>

          <div>
            <label htmlFor="start_date" className={LABEL_CLASS}>
              Data de início <span className="text-red-500">*</span>
            </label>
            <input
              id="start_date"
              type="date"
              className={INPUT_CLASS}
              value={form.start_date}
              onChange={(e) => set('start_date', e.target.value)}
            />
            <FieldError field="start_date" />
          </div>
        </div>

        <div className="flex gap-3 mt-6 pt-4 border-t border-slate-100 justify-end">
          <button onClick={handleClose} disabled={submitting} className={SECONDARY_BTN}>
            Cancelar
          </button>
          <button onClick={handleSubmit} disabled={!canSubmit} className={PRIMARY_BTN}>
            {submitting ? 'Salvando...' : 'Criar Lotação'}
          </button>
        </div>
      </div>
    </div>
  )
}
