'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'

interface ReleaseBedModalProps {
  bedId: string
  bedIdentifier: string
  onClose: () => void
  onReleased: () => void
}

/**
 * Liberar leito (beds.housekeeping) — close the housekeeping cycle via
 * POST /api/v1/beds/{id}/release/ {reason?}, taking a bed em `higienização` back
 * to `livre`. Only higienização→livre is allowed server-side; a 409 surfaces as a
 * friendly message (e.g. the bed is no longer being cleaned).
 */
export default function ReleaseBedModal({
  bedId,
  bedIdentifier,
  onClose,
  onReleased,
}: ReleaseBedModalProps) {
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setSubmitting(true)
    setError(null)
    const body: Record<string, string> = {}
    if (reason.trim()) body.reason = reason.trim()
    try {
      await apiFetch(`/api/v1/beds/${bedId}/release/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onReleased()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Não foi possível liberar — o leito não está em higienização.')
        return
      }
      setError('Não foi possível liberar o leito. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Liberar leito"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Liberar leito</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Leito <span className="font-mono">{bedIdentifier}</span> — higienização concluída,
            devolver para livre.
          </p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Motivo (opcional)</span>
          <textarea
            aria-label="Motivo da liberação"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            placeholder="Observações sobre a higienização..."
          />
        </label>

        {error && <p className="text-sm font-semibold text-red-700">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-panel"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Liberando...' : 'Confirmar liberação'}
          </button>
        </div>
      </div>
    </div>
  )
}
