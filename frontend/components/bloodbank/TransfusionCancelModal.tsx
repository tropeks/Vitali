'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import { apiErrorDetail } from './bloodbank-types'

interface TransfusionCancelModalProps {
  requestId: string
  onClose: () => void
  onCancelled: () => void
}

/**
 * Cancelar requisição (hemoterapia.manage) — POST
 * /api/v1/transfusion-requests/{id}/cancelar/ {reason}. A reserved bag is freed
 * server-side by the transfusion service; an illegal-transition 409 surfaces as
 * a friendly message.
 */
export default function TransfusionCancelModal({
  requestId,
  onClose,
  onCancelled,
}: TransfusionCancelModalProps) {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch(`/api/v1/transfusion-requests/${requestId}/cancelar/`, {
        method: 'POST',
        body: JSON.stringify({ reason: reason.trim() }),
      })
      onCancelled()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(
          apiErrorDetail(err.body, 'Não é possível cancelar esta requisição na situação atual.')
        )
        return
      }
      setError('Não foi possível cancelar a requisição. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Cancelar requisição transfusional"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-neu-modal">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Cancelar requisição</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            A bolsa reservada, se houver, será liberada de volta ao estoque.
          </p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Motivo (opcional)</span>
          <textarea
            aria-label="Motivo do cancelamento"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            placeholder="Motivo do cancelamento..."
          />
        </label>

        {error && <p className="text-sm font-semibold text-red-700">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-slate-50"
          >
            Voltar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-md bg-neu-danger px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Cancelando...' : 'Cancelar requisição'}
          </button>
        </div>
      </div>
    </div>
  )
}
