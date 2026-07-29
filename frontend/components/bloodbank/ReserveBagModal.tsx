'use client'

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  aboRhLabel,
  apiErrorDetail,
  formatDate,
  normalizeList,
  type BloodBagDTO,
  type ListResponse,
  type TransfusionRequestDTO,
} from './bloodbank-types'

interface ReserveBagModalProps {
  request: TransfusionRequestDTO
  onClose: () => void
  onReserved: () => void
}

/**
 * Reservar bolsa (hemoterapia.manage) — chooses a compatible available bag for
 * a solicitada request and POSTs /api/v1/transfusion-requests/{id}/reservar/
 * {bag}. Candidate bags are the available stock of the requested hemocomponente
 * (GET /blood-bags/?available=true&component=). The backend runs the ABO/Rh +
 * crossmatch compatibility check and returns 409 when the bag is
 * incompatible/unavailable, surfaced here as a friendly message.
 */
export default function ReserveBagModal({ request, onClose, onReserved }: ReserveBagModalProps) {
  const [bags, setBags] = useState<BloodBagDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiFetch<ListResponse<BloodBagDTO> | BloodBagDTO[]>(
        `/api/v1/blood-bags/?available=true&component=${request.component}`
      )
      setBags(normalizeList(data))
    } catch {
      setBags([])
    } finally {
      setLoading(false)
    }
  }, [request.component])

  useEffect(() => {
    load()
  }, [load])

  async function submit() {
    if (!selected) {
      setError('Selecione uma bolsa compatível para reservar.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch(`/api/v1/transfusion-requests/${request.id}/reservar/`, {
        method: 'POST',
        body: JSON.stringify({ bag: selected }),
      })
      onReserved()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(
          apiErrorDetail(
            err.body,
            'Bolsa incompatível ou indisponível — escolha outra bolsa.'
          )
        )
        return
      }
      setError('Não foi possível reservar a bolsa. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Reservar bolsa"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-neu-modal">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={18} className="text-neu-brand" aria-hidden />
            <div>
              <h2 className="text-base font-semibold text-neu-ink">Reservar bolsa</h2>
              <p className="text-xs text-neu-inkMuted">
                {request.component_display ?? request.component_code ?? 'Hemocomponente'} ·{' '}
                {request.quantidade} un.
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
          {loading ? (
            <SectionState
              title="Buscando bolsas disponíveis..."
              detail="Carregando o estoque compatível para esta requisição."
            />
          ) : bags.length === 0 ? (
            <SectionState
              title="Nenhuma bolsa disponível"
              detail="Não há bolsas liberadas e disponíveis do hemocomponente solicitado."
              tone="warning"
            />
          ) : (
            <fieldset className="space-y-2" aria-label="Bolsas disponíveis">
              <legend className="sr-only">Bolsas disponíveis</legend>
              {bags.map((bag) => (
                <label
                  key={bag.id}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${
                    selected === bag.id
                      ? 'border-neu-brand bg-blue-50'
                      : 'border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="reserve-bag"
                      value={bag.id}
                      checked={selected === bag.id}
                      onChange={() => setSelected(bag.id)}
                    />
                    <span className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-1.5 py-0.5 text-xs font-bold text-red-700">
                      {aboRhLabel(bag.abo, bag.rh_factor)}
                    </span>
                    <span className="font-mono text-xs text-neu-inkMuted">{bag.identifier}</span>
                  </div>
                  <span className="text-xs text-neu-inkMuted">
                    {bag.volume_ml} mL · val. {formatDate(bag.expiry_date)}
                  </span>
                </label>
              ))}
            </fieldset>
          )}

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
            disabled={submitting || bags.length === 0}
            className="rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? 'Reservando...' : 'Reservar bolsa'}
          </button>
        </div>
      </div>
    </div>
  )
}
