'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import { DISPOSITION_OPTIONS } from './inpatient-types'

interface DischargeModalProps {
  admissionId: string
  patientName: string
  onClose: () => void
  onDischarged: () => void
}

/**
 * Dar alta (adt.discharge) — close an active admission via
 * POST /api/v1/admissions/{id}/discharge/ {disposition, reason?}. The bed is
 * freed server-side by the ADT service; a 409 surfaces as a friendly message.
 */
export default function DischargeModal({
  admissionId,
  patientName,
  onClose,
  onDischarged,
}: DischargeModalProps) {
  const [disposition, setDisposition] = useState(DISPOSITION_OPTIONS[0].value)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setSubmitting(true)
    setError(null)
    const body: Record<string, string> = { disposition }
    if (reason.trim()) body.reason = reason.trim()
    try {
      await apiFetch(`/api/v1/admissions/${admissionId}/discharge/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onDischarged()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Não foi possível dar alta — a internação já foi encerrada.')
        return
      }
      setError('Não foi possível dar alta. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Dar alta"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Dar alta</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">{patientName}</p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Desfecho da alta</span>
          <select
            aria-label="Desfecho da alta"
            value={disposition}
            onChange={(e) => setDisposition(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
          >
            {DISPOSITION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Motivo (opcional)</span>
          <textarea
            aria-label="Motivo da alta"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            placeholder="Observações sobre o desfecho..."
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
            {submitting ? 'Registrando...' : 'Confirmar alta'}
          </button>
        </div>
      </div>
    </div>
  )
}
