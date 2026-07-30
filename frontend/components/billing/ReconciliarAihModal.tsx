'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'

interface Props {
  aihId: number
  numeroAtual: string
  onClose: () => void
  onReconciled: () => void
}

/**
 * Reconciliar AIH (sus.write) — informa o número oficial de 13 dígitos do gestor
 * via POST /api/v1/billing/aih-autorizacoes/{id}/reconciliar/ {numero_oficial,
 * data_autorizacao?}. Situação → autorizada (substitui o provisório do bridge).
 * Número inválido/duplicado ou AIH já autorizada → 409 (mensagem amigável).
 */
export default function ReconciliarAihModal({ aihId, numeroAtual, onClose, onReconciled }: Props) {
  const [numeroOficial, setNumeroOficial] = useState('')
  const [dataAutorizacao, setDataAutorizacao] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const valid = /^\d{13}$/.test(numeroOficial.trim())

  async function submit() {
    setSubmitting(true)
    setError(null)
    const body: Record<string, string> = { numero_oficial: numeroOficial.trim() }
    if (dataAutorizacao) body.data_autorizacao = dataAutorizacao
    try {
      await apiFetch(`/api/v1/billing/aih-autorizacoes/${aihId}/reconciliar/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onReconciled()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Número inválido/duplicado ou AIH já autorizada.')
        return
      }
      setError('Não foi possível reconciliar a AIH. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Reconciliar AIH"
    >
      <div className="w-full max-w-md space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Reconciliar AIH</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Número atual: <span className="font-mono">{numeroAtual}</span>
          </p>
        </div>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Número oficial (13 dígitos)</span>
          <input
            aria-label="Número oficial"
            value={numeroOficial}
            onChange={(e) => setNumeroOficial(e.target.value)}
            inputMode="numeric"
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 font-mono text-neu-ink"
            placeholder="0000000000000"
          />
          {numeroOficial.trim() !== '' && !valid && (
            <span className="mt-1 block text-xs font-semibold text-red-700">
              O número oficial deve ter exatamente 13 dígitos.
            </span>
          )}
        </label>

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Data da autorização (opcional)</span>
          <input
            type="date"
            aria-label="Data da autorização"
            value={dataAutorizacao}
            onChange={(e) => setDataAutorizacao(e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
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
            disabled={submitting || !valid}
            className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Reconciliando...' : 'Confirmar reconciliação'}
          </button>
        </div>
      </div>
    </div>
  )
}
