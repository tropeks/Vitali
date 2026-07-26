'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import type { LeaveRequest } from '@/app/(dashboard)/rh/afastamentos/page'

/**
 * Maker-checker decide modal. POSTs to
 * /api/v1/hr/leave-requests/<id>/decide/ with { approve: bool, note: str }.
 * The server blocks self-approval; if it rejects the decision, its
 * error message is surfaced verbatim.
 */

export interface LeaveDecideModalProps {
  open: boolean
  request: LeaveRequest | null
  onClose: () => void
  onDecided: () => void
}

const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'
const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-slate-400'
const SECONDARY_BTN =
  'border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors'
const APPROVE_BTN =
  'bg-green-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
const REJECT_BTN =
  'bg-red-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'

function extractError(body: any): string {
  if (!body) return 'Erro ao registrar a decisão. Tente novamente.'
  if (typeof body === 'string') return body
  if (body.detail) return String(body.detail)
  const firstVal = Object.values(body)[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao registrar a decisão. Tente novamente.'
}

export default function LeaveDecideModal({
  open,
  request,
  onClose,
  onDecided,
}: LeaveDecideModalProps) {
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!open || !request) return null

  const handleClose = () => {
    if (submitting) return
    setNotes('')
    setError('')
    onClose()
  }

  const decide = async (decision: 'approve' | 'reject') => {
    setSubmitting(true)
    setError('')

    try {
      await apiFetch(`/api/v1/hr/leave-requests/${request.id}/decide/`, {
        method: 'POST',
        body: JSON.stringify({ approve: decision === 'approve', note: notes.trim() }),
      })
      setNotes('')
      onDecided()
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
            <h2 className="text-base font-semibold text-slate-900">Decidir afastamento</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Você não pode aprovar uma solicitação feita por você.
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

        <div className="flex-1 overflow-y-auto space-y-3">
          <dl className="text-sm text-slate-700 space-y-1">
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Funcionário</dt>
              <dd className="font-medium">{request.employee_name ?? request.employee}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Tipo</dt>
              <dd>{request.leave_type_display ?? request.leave_type}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Período</dt>
              <dd>
                {request.start_date} — {request.end_date}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Motivo</dt>
              <dd className="text-right">{request.reason}</dd>
            </div>
          </dl>

          <div>
            <label htmlFor="decide_notes" className={LABEL_CLASS}>
              Observações (opcional)
            </label>
            <textarea
              id="decide_notes"
              rows={3}
              className={INPUT_CLASS}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Justifique sua decisão, se necessário"
            />
          </div>
        </div>

        <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100">
          <button onClick={handleClose} disabled={submitting} className={SECONDARY_BTN}>
            Cancelar
          </button>
          <div className="flex gap-2">
            <button
              onClick={() => decide('reject')}
              disabled={submitting}
              className={REJECT_BTN}
            >
              {submitting ? '...' : 'Rejeitar'}
            </button>
            <button
              onClick={() => decide('approve')}
              disabled={submitting}
              className={APPROVE_BTN}
            >
              {submitting ? '...' : 'Aprovar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
