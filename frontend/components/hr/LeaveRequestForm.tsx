'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'

/**
 * Create-a-leave-request modal. POSTs to /api/v1/hr/leave-requests/ with only
 * the writable fields — status/approval/requested_by/created_at/updated_at are
 * server-set and never sent. Surfaces DRF field/detail errors inline.
 */

export interface LeaveEmployeeOption {
  id: string
  full_name: string
}

export interface LeaveRequestFormProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  employees: LeaveEmployeeOption[]
}

// Values MUST match backend LeaveRequest.Type (apps/hr/rh_models.py). Sending
// pt-BR slugs (ferias/licenca_medica/…) makes the API reject the request with 400.
const LEAVE_TYPES: { value: string; label: string }[] = [
  { value: 'vacation', label: 'Férias' },
  { value: 'sick', label: 'Afastamento médico' },
  { value: 'maternity', label: 'Licença-maternidade' },
  { value: 'paternity', label: 'Licença-paternidade' },
  { value: 'unpaid', label: 'Licença não remunerada' },
  { value: 'other', label: 'Outro' },
]

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-slate-400'
const SELECT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white'
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'
const PRIMARY_BTN =
  'bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
const SECONDARY_BTN =
  'border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors'

const INITIAL = {
  employee: '',
  leave_type: 'vacation',
  start_date: '',
  end_date: '',
  reason: '',
}

function extractError(body: any): string {
  if (!body) return 'Erro ao solicitar afastamento. Tente novamente.'
  if (typeof body === 'string') return body
  if (body.detail) return String(body.detail)
  const firstVal = Object.values(body)[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao solicitar afastamento. Tente novamente.'
}

export default function LeaveRequestForm({
  open,
  onClose,
  onSuccess,
  employees,
}: LeaveRequestFormProps) {
  const [form, setForm] = useState({ ...INITIAL })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!open) return null

  const set = (key: keyof typeof INITIAL, value: string) =>
    setForm((f) => ({ ...f, [key]: value }))

  const isValid =
    form.employee !== '' &&
    form.leave_type !== '' &&
    form.start_date !== '' &&
    form.end_date !== '' &&
    form.reason.trim() !== ''

  const handleClose = () => {
    if (submitting) return
    setForm({ ...INITIAL })
    setError('')
    onClose()
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')

    const payload = {
      employee: form.employee,
      leave_type: form.leave_type,
      start_date: form.start_date,
      end_date: form.end_date,
      reason: form.reason.trim(),
    }

    try {
      await apiFetch('/api/v1/hr/leave-requests/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setForm({ ...INITIAL })
      onSuccess()
    } catch (err) {
      if (err instanceof ApiError) {
        setError(extractError(err.body))
      } else {
        setError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-lg w-full max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Solicitar afastamento</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              A aprovação é feita por outro gestor de RH (maker-checker).
            </p>
          </div>
          <button
            onClick={handleClose}
            disabled={submitting}
            className="text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-4">
          <div>
            <label htmlFor="leave_employee" className={LABEL_CLASS}>
              Funcionário <span className="text-red-500">*</span>
            </label>
            <select
              id="leave_employee"
              className={SELECT_CLASS}
              value={form.employee}
              onChange={(e) => set('employee', e.target.value)}
            >
              <option value="">Selecione...</option>
              {employees.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.full_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="leave_type" className={LABEL_CLASS}>
              Tipo de afastamento <span className="text-red-500">*</span>
            </label>
            <select
              id="leave_type"
              className={SELECT_CLASS}
              value={form.leave_type}
              onChange={(e) => set('leave_type', e.target.value)}
            >
              {LEAVE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="leave_start" className={LABEL_CLASS}>
                Início <span className="text-red-500">*</span>
              </label>
              <input
                id="leave_start"
                type="date"
                className={INPUT_CLASS}
                value={form.start_date}
                onChange={(e) => set('start_date', e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="leave_end" className={LABEL_CLASS}>
                Fim <span className="text-red-500">*</span>
              </label>
              <input
                id="leave_end"
                type="date"
                className={INPUT_CLASS}
                value={form.end_date}
                onChange={(e) => set('end_date', e.target.value)}
              />
            </div>
          </div>

          <div>
            <label htmlFor="leave_reason" className={LABEL_CLASS}>
              Motivo / justificativa <span className="text-red-500">*</span>
            </label>
            <textarea
              id="leave_reason"
              rows={3}
              className={INPUT_CLASS}
              value={form.reason}
              onChange={(e) => set('reason', e.target.value)}
              placeholder="Descreva o motivo do afastamento"
            />
          </div>
        </div>

        <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100">
          <button onClick={handleClose} disabled={submitting} className={SECONDARY_BTN}>
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={!isValid || submitting}
            className={PRIMARY_BTN}
          >
            {submitting ? 'Enviando...' : 'Solicitar afastamento'}
          </button>
        </div>
      </div>
    </div>
  )
}
