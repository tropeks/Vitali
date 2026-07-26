'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'

/**
 * Create-an-ASO (OccupationalHealthExam) modal. POSTs to
 * /api/v1/hr/occupational-health-exams/ with only the writable fields —
 * id/recorded_by/created_at/updated_at are server-set and never sent.
 * Mirrors LeaveRequestForm's structure.
 */

export interface AsoEmployeeOption {
  id: string
  full_name: string
}

export interface AsoFormProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
  employees: AsoEmployeeOption[]
}

const EXAM_TYPES: { value: string; label: string }[] = [
  { value: 'admission', label: 'Admissional' },
  { value: 'periodic', label: 'Periódico' },
  { value: 'return', label: 'Retorno ao trabalho' },
  { value: 'role_change', label: 'Mudança de risco' },
  { value: 'termination', label: 'Demissional' },
]

const RESULTS: { value: string; label: string }[] = [
  { value: 'pending', label: 'Pendente' },
  { value: 'fit', label: 'Apto' },
  { value: 'unfit', label: 'Inapto' },
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
  exam_type: 'periodic',
  performed_on: '',
  expires_on: '',
  result: 'pending',
  provider_name: '',
  certificate_reference: '',
  restrictions: '',
}

function extractError(body: any): string {
  if (!body) return 'Erro ao registrar ASO. Tente novamente.'
  if (typeof body === 'string') return body
  if (body.detail) return String(body.detail)
  const firstVal = Object.values(body)[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao registrar ASO. Tente novamente.'
}

export default function AsoForm({ open, onClose, onSuccess, employees }: AsoFormProps) {
  const [form, setForm] = useState({ ...INITIAL })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!open) return null

  const set = (key: keyof typeof INITIAL, value: string) =>
    setForm((f) => ({ ...f, [key]: value }))

  const isValid =
    form.employee !== '' &&
    form.exam_type !== '' &&
    form.performed_on !== '' &&
    form.provider_name.trim() !== ''

  const handleClose = () => {
    if (submitting) return
    setForm({ ...INITIAL })
    setError('')
    onClose()
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')

    const payload: Record<string, unknown> = {
      employee: form.employee,
      exam_type: form.exam_type,
      performed_on: form.performed_on,
      result: form.result,
      provider_name: form.provider_name.trim(),
    }
    if (form.expires_on.trim() !== '') payload.expires_on = form.expires_on
    if (form.certificate_reference.trim() !== '') {
      payload.certificate_reference = form.certificate_reference.trim()
    }
    if (form.restrictions.trim() !== '') payload.restrictions = form.restrictions.trim()

    try {
      await apiFetch('/api/v1/hr/occupational-health-exams/', {
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
            <h2 className="text-base font-semibold text-slate-900">Registrar ASO</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Atestado de Saúde Ocupacional — lifecycle sem achados clínicos armazenados em RH.
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
            <label htmlFor="aso_employee" className={LABEL_CLASS}>
              Funcionário <span className="text-red-500">*</span>
            </label>
            <select
              id="aso_employee"
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
            <label htmlFor="aso_exam_type" className={LABEL_CLASS}>
              Tipo de exame <span className="text-red-500">*</span>
            </label>
            <select
              id="aso_exam_type"
              className={SELECT_CLASS}
              value={form.exam_type}
              onChange={(e) => set('exam_type', e.target.value)}
            >
              {EXAM_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="aso_performed_on" className={LABEL_CLASS}>
                Data do exame <span className="text-red-500">*</span>
              </label>
              <input
                id="aso_performed_on"
                type="date"
                className={INPUT_CLASS}
                value={form.performed_on}
                onChange={(e) => set('performed_on', e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="aso_expires_on" className={LABEL_CLASS}>
                Vencimento <span className="text-slate-400 font-normal">(opcional)</span>
              </label>
              <input
                id="aso_expires_on"
                type="date"
                className={INPUT_CLASS}
                value={form.expires_on}
                onChange={(e) => set('expires_on', e.target.value)}
              />
            </div>
          </div>

          <div>
            <label htmlFor="aso_result" className={LABEL_CLASS}>
              Resultado <span className="text-red-500">*</span>
            </label>
            <select
              id="aso_result"
              className={SELECT_CLASS}
              value={form.result}
              onChange={(e) => set('result', e.target.value)}
            >
              {RESULTS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="aso_provider_name" className={LABEL_CLASS}>
              Médico <span className="text-red-500">*</span>
            </label>
            <input
              id="aso_provider_name"
              type="text"
              className={INPUT_CLASS}
              value={form.provider_name}
              onChange={(e) => set('provider_name', e.target.value)}
              placeholder="Nome do médico / clínica responsável"
            />
          </div>

          <div>
            <label htmlFor="aso_certificate_reference" className={LABEL_CLASS}>
              Referência do certificado <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <input
              id="aso_certificate_reference"
              type="text"
              className={INPUT_CLASS}
              value={form.certificate_reference}
              onChange={(e) => set('certificate_reference', e.target.value)}
            />
          </div>

          <div>
            <label htmlFor="aso_restrictions" className={LABEL_CLASS}>
              Restrições <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <textarea
              id="aso_restrictions"
              rows={3}
              className={INPUT_CLASS}
              value={form.restrictions}
              onChange={(e) => set('restrictions', e.target.value)}
            />
          </div>
        </div>

        <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100">
          <button onClick={handleClose} disabled={submitting} className={SECONDARY_BTN}>
            Cancelar
          </button>
          <button onClick={handleSubmit} disabled={!isValid || submitting} className={PRIMARY_BTN}>
            {submitting ? 'Registrando...' : 'Registrar ASO'}
          </button>
        </div>
      </div>
    </div>
  )
}
