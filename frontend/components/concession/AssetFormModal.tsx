'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  ASSET_STATUS_OPTIONS,
  OWNERSHIP_OPTIONS,
  unwrap,
  type Asset,
  type AssetStatus,
  type AssetOwnership,
  type FacilityOption,
  type Listish,
} from './assetMeta'

/**
 * AssetFormModal — create / edit an EquipmentAsset (comodato fleet).
 * Mirrors EquipmentAssetSerializer writable fields. `monthly_depreciation`
 * is server-computed (read-only) and never sent.
 * Create → POST /api/v1/concession/assets/, edit → PUT the detail endpoint.
 */

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

function extractFieldErrors(body: any): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [key, val] of Object.entries(body)) {
    if (Array.isArray(val) && val.length > 0) errors[key] = String(val[0])
    else if (typeof val === 'string') errors[key] = val
  }
  return errors
}

export interface AssetFormModalProps {
  open: boolean
  asset?: Asset | null
  onClose: () => void
  onSuccess?: (asset: Asset) => void
}

export default function AssetFormModal({
  open,
  asset = null,
  onClose,
  onSuccess,
}: AssetFormModalProps) {
  const isEdit = asset != null

  const [assetTag, setAssetTag] = useState('')
  const [name, setName] = useState('')
  const [model, setModel] = useState('')
  const [serialNumber, setSerialNumber] = useState('')
  const [status, setStatus] = useState<AssetStatus>('ACTIVE')
  const [ownership, setOwnership] = useState<AssetOwnership>('OPERATOR')
  const [purchaseCost, setPurchaseCost] = useState('')
  const [usefulLife, setUsefulLife] = useState('')
  const [purchaseDate, setPurchaseDate] = useState('')
  const [currentLocation, setCurrentLocation] = useState('')
  const [active, setActive] = useState(true)

  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')

  // Seed the form whenever the modal opens (or the edited asset changes).
  useEffect(() => {
    if (!open) return
    setAssetTag(asset?.asset_tag ?? '')
    setName(asset?.name ?? '')
    setModel(asset?.model ?? '')
    setSerialNumber(asset?.serial_number ?? '')
    setStatus(asset?.status ?? 'ACTIVE')
    setOwnership(asset?.ownership ?? 'OPERATOR')
    setPurchaseCost(asset?.purchase_cost ?? '')
    setUsefulLife(asset?.useful_life_months != null ? String(asset.useful_life_months) : '')
    setPurchaseDate(asset?.purchase_date ?? '')
    setCurrentLocation(asset?.current_location ?? '')
    setActive(asset?.active ?? true)
    setFieldErrors({})
    setGlobalError('')
  }, [open, asset])

  // Load facilities for the location select.
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

  const valid = assetTag.trim().length > 0 && model.trim().length > 0

  async function handleSubmit() {
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const payload = {
      asset_tag: assetTag.trim(),
      name: name.trim(),
      model: model.trim(),
      serial_number: serialNumber.trim(),
      status,
      ownership,
      purchase_cost: purchaseCost.trim() === '' ? null : purchaseCost.trim(),
      useful_life_months: usefulLife.trim() === '' ? null : Number(usefulLife),
      purchase_date: purchaseDate === '' ? null : purchaseDate,
      current_location: currentLocation === '' ? null : currentLocation,
      active,
    }

    const path = isEdit
      ? `/api/v1/concession/assets/${asset!.id}/`
      : '/api/v1/concession/assets/'

    try {
      const saved = await apiFetch<Asset>(path, {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess?.(saved)
      onClose()
    } catch (err) {
      if (err instanceof ApiError) {
        const errors = extractFieldErrors(err.body)
        if (Object.keys(errors).length > 0) setFieldErrors(errors)
        else setGlobalError('Não foi possível salvar o ativo.')
      } else {
        setGlobalError('Não foi possível salvar o ativo.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {isEdit ? 'Editar ativo' : 'Novo ativo'}
          </h2>
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

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="asset-tag" className={LABEL_CLASS}>
                Patrimônio / Tag
              </label>
              <input
                id="asset-tag"
                className={INPUT_CLASS}
                value={assetTag}
                onChange={(e) => setAssetTag(e.target.value)}
              />
              {fieldErrors.asset_tag && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.asset_tag}</p>
              )}
            </div>
            <div>
              <label htmlFor="asset-name" className={LABEL_CLASS}>
                Nome
              </label>
              <input
                id="asset-name"
                className={INPUT_CLASS}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="asset-model" className={LABEL_CLASS}>
                Modelo
              </label>
              <input
                id="asset-model"
                className={INPUT_CLASS}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
              {fieldErrors.model && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.model}</p>
              )}
            </div>
            <div>
              <label htmlFor="asset-serial" className={LABEL_CLASS}>
                Número de série
              </label>
              <input
                id="asset-serial"
                className={INPUT_CLASS}
                value={serialNumber}
                onChange={(e) => setSerialNumber(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="asset-status" className={LABEL_CLASS}>
                Status
              </label>
              <select
                id="asset-status"
                className={SELECT_CLASS}
                value={status}
                onChange={(e) => setStatus(e.target.value as AssetStatus)}
              >
                {ASSET_STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="asset-ownership" className={LABEL_CLASS}>
                Propriedade
              </label>
              <select
                id="asset-ownership"
                className={SELECT_CLASS}
                value={ownership}
                onChange={(e) => setOwnership(e.target.value as AssetOwnership)}
              >
                {OWNERSHIP_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="asset-cost" className={LABEL_CLASS}>
                Custo de aquisição (R$)
              </label>
              <input
                id="asset-cost"
                type="text"
                inputMode="decimal"
                className={INPUT_CLASS}
                value={purchaseCost}
                onChange={(e) => setPurchaseCost(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="asset-life" className={LABEL_CLASS}>
                Vida útil (meses)
              </label>
              <input
                id="asset-life"
                type="number"
                min={0}
                className={INPUT_CLASS}
                value={usefulLife}
                onChange={(e) => setUsefulLife(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="asset-purchase-date" className={LABEL_CLASS}>
                Data de aquisição
              </label>
              <input
                id="asset-purchase-date"
                type="date"
                className={INPUT_CLASS}
                value={purchaseDate}
                onChange={(e) => setPurchaseDate(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="asset-location" className={LABEL_CLASS}>
                Localização atual
              </label>
              <select
                id="asset-location"
                className={SELECT_CLASS}
                value={currentLocation}
                onChange={(e) => setCurrentLocation(e.target.value)}
              >
                <option value="">Armazém (não implantado)</option>
                {facilities.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
            />
            Ativo (em uso na frota)
          </label>
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
            disabled={!valid || submitting}
            className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Salvando...' : isEdit ? 'Salvar' : 'Criar ativo'}
          </button>
        </div>
      </div>
    </div>
  )
}
