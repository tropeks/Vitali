'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  MOVEMENT_TYPE_OPTIONS,
  unwrap,
  type Asset,
  type AssetMovement,
  type FacilityOption,
  type Listish,
  type MovementType,
} from './assetMeta'

/**
 * AssetMovementModal — record an append-only asset movement
 * (deploy / retrieve / transfer / swap). POSTs to
 * /api/v1/concession/asset-movements/; the server auto-relocates the asset.
 * Which location fields matter depends on movement_type:
 *   DEPLOYMENT → to_facility, RETRIEVAL → from_facility,
 *   TRANSFER → from + to, SWAP → swapped_with.
 */

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

export interface AssetMovementModalProps {
  open: boolean
  asset: Asset
  /** Other assets, used as the SWAP counterpart options. */
  assets?: Asset[]
  onClose: () => void
  onSuccess?: (movement: AssetMovement) => void
}

export default function AssetMovementModal({
  open,
  asset,
  assets = [],
  onClose,
  onSuccess,
}: AssetMovementModalProps) {
  const [movementType, setMovementType] = useState<MovementType>('DEPLOYMENT')
  const [fromFacility, setFromFacility] = useState('')
  const [toFacility, setToFacility] = useState('')
  const [swappedWith, setSwappedWith] = useState('')
  const [notes, setNotes] = useState('')

  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [globalError, setGlobalError] = useState('')

  useEffect(() => {
    if (!open) return
    setMovementType('DEPLOYMENT')
    setFromFacility(asset?.current_location ?? '')
    setToFacility('')
    setSwappedWith('')
    setNotes('')
    setGlobalError('')
  }, [open, asset])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/')
      .then((data) => {
        if (!cancelled) setFacilities(unwrap(data))
      })
      .catch(() => {
        if (!cancelled) setFacilities([])
      })
    return () => {
      cancelled = true
    }
  }, [open])

  if (!open) return null

  const showFrom = movementType === 'RETRIEVAL' || movementType === 'TRANSFER'
  const showTo = movementType === 'DEPLOYMENT' || movementType === 'TRANSFER'
  const showSwap = movementType === 'SWAP'

  async function handleSubmit() {
    setSubmitting(true)
    setGlobalError('')

    const payload = {
      movement_type: movementType,
      asset: asset.id,
      from_facility: showFrom && fromFacility !== '' ? fromFacility : null,
      to_facility: showTo && toFacility !== '' ? toFacility : null,
      swapped_with: showSwap && swappedWith !== '' ? swappedWith : null,
      notes: notes.trim(),
    }

    try {
      const saved = await apiFetch<AssetMovement>('/api/v1/concession/asset-movements/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess?.(saved)
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.body?.detail) {
        setGlobalError(String(err.body.detail))
      } else {
        setGlobalError('Não foi possível registrar a movimentação.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Movimentar ativo</h2>
            <p className="text-xs text-slate-500">
              {asset.asset_tag} — {asset.model}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-600"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {globalError && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {globalError}
            </p>
          )}

          <div>
            <label htmlFor="movement-type" className={LABEL_CLASS}>
              Tipo de movimentação
            </label>
            <select
              id="movement-type"
              className={SELECT_CLASS}
              value={movementType}
              onChange={(e) => setMovementType(e.target.value as MovementType)}
            >
              {MOVEMENT_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          {showFrom && (
            <div>
              <label htmlFor="movement-from" className={LABEL_CLASS}>
                Origem
              </label>
              <select
                id="movement-from"
                className={SELECT_CLASS}
                value={fromFacility}
                onChange={(e) => setFromFacility(e.target.value)}
              >
                <option value="">Armazém</option>
                {facilities.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {showTo && (
            <div>
              <label htmlFor="movement-to" className={LABEL_CLASS}>
                Destino
              </label>
              <select
                id="movement-to"
                className={SELECT_CLASS}
                value={toFacility}
                onChange={(e) => setToFacility(e.target.value)}
              >
                <option value="">Armazém</option>
                {facilities.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {showSwap && (
            <div>
              <label htmlFor="movement-swap" className={LABEL_CLASS}>
                Trocar com
              </label>
              <select
                id="movement-swap"
                className={SELECT_CLASS}
                value={swappedWith}
                onChange={(e) => setSwappedWith(e.target.value)}
              >
                <option value="">Selecione o equipamento</option>
                {assets
                  .filter((a) => a.id !== asset.id)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.asset_tag} — {a.model}
                    </option>
                  ))}
              </select>
            </div>
          )}

          <div>
            <label htmlFor="movement-notes" className={LABEL_CLASS}>
              Observações
            </label>
            <textarea
              id="movement-notes"
              rows={2}
              className={INPUT_CLASS}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Registrando...' : 'Registrar movimentação'}
          </button>
        </div>
      </div>
    </div>
  )
}
