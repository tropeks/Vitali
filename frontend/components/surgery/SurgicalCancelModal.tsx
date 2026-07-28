'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'

interface SurgicalCancelModalProps {
  caseId: string
  patientName: string
  onClose: () => void
  onCancelled: () => void
}

/**
 * Cancelar cirurgia (surgery.schedule) — POST /surgical-cases/{id}/cancel/
 * with an optional reason. The case moves to `cancelada` (freeing the room
 * slot). An illegal transition (already finished/cancelled) returns 409 and is
 * surfaced inline.
 */
export default function SurgicalCancelModal({
  caseId,
  patientName,
  onClose,
  onCancelled,
}: SurgicalCancelModalProps) {
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setSaving(true)
    setError('')
    const body: Record<string, string> = {}
    if (reason.trim()) body.reason = reason.trim()
    try {
      await apiFetch(`/api/v1/surgical-cases/${caseId}/cancel/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onCancelled()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Não é possível cancelar este caso na situação atual.')
        return
      }
      setError('Não foi possível cancelar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Cancelar cirurgia"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Cancelar cirurgia</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">{patientName}</p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Motivo (opcional)</span>
          <textarea
            aria-label="Motivo do cancelamento"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            placeholder="Ex.: paciente sem condições clínicas, remarcação..."
          />
        </label>

        {error && <p className="text-sm font-semibold text-red-700">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-panel"
          >
            Voltar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            {saving ? 'Cancelando...' : 'Cancelar cirurgia'}
          </button>
        </div>
      </div>
    </div>
  )
}
