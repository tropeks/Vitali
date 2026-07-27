'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import type { BoardBed } from './inpatient-types'

interface TransferBedModalProps {
  admissionId: string
  patientName: string
  /** Candidate destinations — beds currently livre. */
  freeBeds: BoardBed[]
  onClose: () => void
  onTransferred: () => void
}

/**
 * Transferir (adt.transfer) — move an active admission to another livre bed via
 * POST /api/v1/admissions/{id}/transfer/ {to_bed, reason?}. A 409 (destination
 * no longer free) is surfaced as a friendly "leito ocupado" message.
 */
export default function TransferBedModal({
  admissionId,
  patientName,
  freeBeds,
  onClose,
  onTransferred,
}: TransferBedModalProps) {
  const [toBed, setToBed] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!toBed) return
    setSubmitting(true)
    setError(null)
    const body: Record<string, string> = { to_bed: toBed }
    if (reason.trim()) body.reason = reason.trim()
    try {
      await apiFetch(`/api/v1/admissions/${admissionId}/transfer/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onTransferred()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Leito ocupado — escolha outro leito livre.')
        return
      }
      setError('Não foi possível transferir. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Transferir leito"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Transferir leito</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">{patientName}</p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Leito de destino</span>
          <select
            aria-label="Leito de destino"
            value={toBed}
            onChange={(e) => setToBed(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
          >
            <option value="">Selecione um leito livre...</option>
            {freeBeds.map((bed) => (
              <option key={bed.id} value={bed.id}>
                {bed.identifier}
              </option>
            ))}
          </select>
        </label>

        {freeBeds.length === 0 && (
          <p className="text-xs text-yellow-800">
            Nenhum leito livre disponível para transferência no momento.
          </p>
        )}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Motivo (opcional)</span>
          <textarea
            aria-label="Motivo da transferência"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            placeholder="Ex.: aproximação de UTI, isolamento..."
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
            disabled={submitting || toBed === ''}
            className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Transferindo...' : 'Transferir'}
          </button>
        </div>
      </div>
    </div>
  )
}
