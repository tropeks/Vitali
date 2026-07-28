'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { MAINTENANCE_ENDPOINTS, type MaintenanceTicket } from './maintenanceMeta'

/**
 * MaintenanceCompleteModal — collects the optional resolution + cost before
 * transitioning a ticket IN_PROGRESS → COMPLETED.
 * POST /api/v1/concession/maintenance-tickets/{id}/complete/
 * Both fields are optional per MaintenanceTicketCompleteInputRequest; an
 * empty resolution / cost is still sent so the caller doesn't have to guess
 * what the server defaults to.
 */

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

export interface MaintenanceCompleteModalProps {
  open: boolean
  ticket: MaintenanceTicket
  onClose: () => void
  onSuccess?: (ticket: MaintenanceTicket) => void
}

export default function MaintenanceCompleteModal({
  open,
  ticket,
  onClose,
  onSuccess,
}: MaintenanceCompleteModalProps) {
  const [resolution, setResolution] = useState('')
  const [cost, setCost] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setResolution('')
    setCost('')
    setError('')
  }, [open, ticket])

  if (!open) return null

  async function handleSubmit() {
    setSubmitting(true)
    setError('')
    try {
      const updated = await apiFetch<MaintenanceTicket>(
        `${MAINTENANCE_ENDPOINTS.tickets}${ticket.id}/complete/`,
        {
          method: 'POST',
          body: JSON.stringify({
            resolution,
            cost: cost.trim() === '' ? null : cost.trim(),
          }),
        }
      )
      onSuccess?.(updated)
      onClose()
    } catch {
      setError('Erro ao concluir o chamado.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Concluir chamado</h2>
            <p className="text-xs text-slate-500">{ticket.description || '—'}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-600"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {error && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </p>
          )}

          <div>
            <label htmlFor="complete-resolution" className={LABEL_CLASS}>
              Resolução
            </label>
            <textarea
              id="complete-resolution"
              rows={3}
              className={INPUT_CLASS}
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              placeholder="O que foi feito para resolver o problema"
            />
          </div>

          <div>
            <label htmlFor="complete-cost" className={LABEL_CLASS}>
              Custo do reparo (R$)
            </label>
            <input
              id="complete-cost"
              type="text"
              inputMode="decimal"
              className={INPUT_CLASS}
              value={cost}
              onChange={(e) => setCost(e.target.value)}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Concluindo...' : 'Concluir chamado'}
          </button>
        </div>
      </div>
    </div>
  )
}
