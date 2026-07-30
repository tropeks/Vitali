'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'

interface Props {
  apacId: number
  numeroAtual: string
  onClose: () => void
  onRejected: () => void
}

/**
 * Rejeitar/glosar APAC (sus.write) — POST /api/v1/billing/apac-autorizacoes/
 * {id}/rejeitar/ {motivo}. Situação → rejeitada. Motivo é obrigatório (validado
 * no cliente e no servidor; 409 vira mensagem amigável).
 */
export default function RejeitarApacModal({ apacId, numeroAtual, onClose, onRejected }: Props) {
  const [motivo, setMotivo] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch(`/api/v1/billing/apac-autorizacoes/${apacId}/rejeitar/`, {
        method: 'POST',
        body: JSON.stringify({ motivo: motivo.trim() }),
      })
      onRejected()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Não foi possível rejeitar — informe um motivo.')
        return
      }
      setError('Não foi possível rejeitar a APAC. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Rejeitar APAC"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Rejeitar APAC</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Número: <span className="font-mono">{numeroAtual}</span>
          </p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Motivo da rejeição</span>
          <textarea
            aria-label="Motivo da rejeição"
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            placeholder="Motivo da glosa/rejeição do gestor..."
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
            disabled={submitting || motivo.trim() === ''}
            className="rounded-md bg-neu-danger px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Rejeitando...' : 'Confirmar rejeição'}
          </button>
        </div>
      </div>
    </div>
  )
}
