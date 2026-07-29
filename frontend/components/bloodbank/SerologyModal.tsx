'use client'

import { useState } from 'react'
import { FlaskConical, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  apiErrorDetail,
  SEROLOGY_PANEL,
  SEROLOGY_RESULT_OPTIONS,
  type BloodBagSerologyDTO,
  type SerologyResult,
} from './bloodbank-types'

interface SerologyModalProps {
  bagId: string
  bagIdentifier: string
  onClose: () => void
  /** Called after a successful POST — `released` reflects the bag outcome. */
  onDone: (released: boolean) => void
}

type PanelState = Record<(typeof SEROLOGY_PANEL)[number]['key'], SerologyResult>

const INITIAL: PanelState = {
  hiv: 'nao_reagente',
  hbsag: 'nao_reagente',
  anti_hbc: 'nao_reagente',
  anti_hcv: 'nao_reagente',
  sifilis: 'nao_reagente',
  chagas: 'nao_reagente',
  htlv: 'nao_reagente',
}

/**
 * Triagem sorológica RDC 34 (hemoterapia.manage) — records the 7 mandatory
 * markers for a quarantined BloodBag via POST /api/v1/blood-bag-serologies/.
 * The backend service flips the bag quarentena → liberada (all não-reagente) or
 * descartada (any reagente/indeterminado); re-testing a non-quarantined bag
 * returns 409, surfaced here as a friendly message.
 */
export default function SerologyModal({
  bagId,
  bagIdentifier,
  onClose,
  onDone,
}: SerologyModalProps) {
  const [panel, setPanel] = useState<PanelState>(INITIAL)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const allNonReactive = SEROLOGY_PANEL.every((m) => panel[m.key] === 'nao_reagente')

  function setMarker(key: (typeof SEROLOGY_PANEL)[number]['key'], value: SerologyResult) {
    setPanel((prev) => ({ ...prev, [key]: value }))
  }

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      const result = await apiFetch<BloodBagSerologyDTO>('/api/v1/blood-bag-serologies/', {
        method: 'POST',
        body: JSON.stringify({ bag: bagId, ...panel, notes: notes.trim() }),
      })
      onDone(Boolean(result?.all_non_reactive))
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(
          apiErrorDetail(
            err.body,
            'Esta bolsa não está em quarentena — a sorologia já foi registrada.'
          )
        )
        return
      }
      setError('Não foi possível registrar a sorologia. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Registrar triagem sorológica"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-neu-modal">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <FlaskConical size={18} className="text-neu-brand" aria-hidden />
            <div>
              <h2 className="text-base font-semibold text-neu-ink">Triagem sorológica (RDC 34)</h2>
              <p className="text-xs text-neu-inkMuted">
                Bolsa <span className="font-mono">{bagIdentifier}</span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <div className="space-y-2">
            {SEROLOGY_PANEL.map((marker) => (
              <label
                key={marker.key}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <span className="font-medium text-neu-ink">{marker.label}</span>
                <select
                  aria-label={marker.label}
                  value={panel[marker.key]}
                  onChange={(e) => setMarker(marker.key, e.target.value as SerologyResult)}
                  className="w-44 rounded-md border border-slate-300 bg-neu-input px-3 py-1.5 text-neu-ink"
                >
                  {SEROLOGY_RESULT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Observações (opcional)</span>
            <textarea
              aria-label="Observações da sorologia"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            />
          </label>

          <p
            className={`rounded-md border px-3 py-2 text-xs font-semibold ${
              allNonReactive
                ? 'border-green-200 bg-green-50 text-green-800'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {allNonReactive
              ? 'Todos não reagentes → a bolsa será LIBERADA.'
              : 'Há marcador reagente/indeterminado → a bolsa será DESCARTADA.'}
          </p>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-neu-inkSoft hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? 'Registrando...' : 'Registrar sorologia'}
          </button>
        </div>
      </div>
    </div>
  )
}
