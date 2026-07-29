'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  REACTION_SEVERITY_OPTIONS,
  REACTION_TYPE_OPTIONS,
  type ReactionGravidade,
  type ReactionTipo,
  type TransfusionAdministration,
  type TransfusionReaction,
  type TransfusionReactionPayload,
} from './transfusion-types'

interface ReactionFormProps {
  administration: TransfusionAdministration
  onClose: () => void
  onSaved: (administration: TransfusionAdministration, reaction: TransfusionReaction) => void
}

/**
 * Registro de reação transfusional (hemovigilância, H6). Attaches a reaction to
 * an administração via `POST /api/v1/transfusion-administrations/<pk>/reacao/`
 * with tipo/gravidade/descrição (required by the backend) + conduta and the
 * hemovigilância notification flag (ANVISA/NOTIVISA).
 */
export default function ReactionForm({ administration, onClose, onSaved }: ReactionFormProps) {
  const [tipo, setTipo] = useState<ReactionTipo>('febril_nao_hemolitica')
  const [gravidade, setGravidade] = useState<ReactionGravidade>('leve')
  const [descricao, setDescricao] = useState('')
  const [conduta, setConduta] = useState('')
  const [notificado, setNotificado] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function submit() {
    setSubmitting(true)
    setError(null)
    const body: TransfusionReactionPayload = {
      tipo,
      gravidade,
      descricao: descricao.trim(),
      conduta: conduta.trim(),
      notificado_hemovigilancia: notificado,
    }
    try {
      const reaction = await apiFetch<TransfusionReaction>(
        `/api/v1/transfusion-administrations/${administration.id}/reacao/`,
        { method: 'POST', body: JSON.stringify(body) },
      )
      onSaved(administration, reaction)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError('Verifique os campos da reação e tente novamente.')
        return
      }
      setError('Erro ao registrar a reação. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Registrar reação transfusional"
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Registrar reação transfusional</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            {administration.bag_identifier ? `Bolsa ${administration.bag_identifier} — ` : ''}
            hemovigilância (ANVISA/NOTIVISA).
          </p>
        </div>

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Tipo de reação</span>
            <select
              aria-label="Tipo de reação"
              value={tipo}
              onChange={(e) => setTipo(e.target.value as ReactionTipo)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            >
              {REACTION_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Gravidade</span>
            <select
              aria-label="Gravidade"
              value={gravidade}
              onChange={(e) => setGravidade(e.target.value as ReactionGravidade)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            >
              {REACTION_SEVERITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Descrição</span>
            <textarea
              aria-label="Descrição"
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              placeholder="Descrição do quadro (ex.: febre, calafrios, urticária durante a infusão)."
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Conduta</span>
            <textarea
              aria-label="Conduta"
              value={conduta}
              onChange={(e) => setConduta(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              placeholder="Conduta adotada (ex.: interrupção da transfusão, antitérmico, suporte)."
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-neu-ink">
            <input
              type="checkbox"
              aria-label="Notificado à hemovigilância"
              checked={notificado}
              onChange={(e) => setNotificado(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="font-medium">Notificado à hemovigilância (NOTIVISA)</span>
          </label>
        </div>

        {error && <p className="text-sm text-red-700">{error}</p>}

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
            disabled={submitting || descricao.trim() === ''}
            className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            Registrar reação
          </button>
        </div>
      </div>
    </div>
  )
}
