'use client'

import { useState } from 'react'
import { X, Plus, Trash2, MapPin } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import {
  LOGISTICS_ENDPOINTS,
  DISCREPANCY_TYPE_OPTIONS,
  type Dispatch,
  type DispatchItem,
  type DiscrepancyType,
  type MaterialOption,
  type ProofOfDelivery,
} from './logisticsMeta'

interface DeliveryModalProps {
  open: boolean
  dispatch: Dispatch
  materials: MaterialOption[]
  onClose: () => void
  onDelivered: (proof: ProofOfDelivery) => void
}

interface DiscrepancyDraft {
  type: DiscrepancyType
  dispatch_item: string
  quantity: string
  notes: string
}

const INPUT_CLASS =
  'w-full rounded-lg border border-slate-200 bg-neu-panel px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500'

function itemMaterial(dispatch: Dispatch, itemId: string): string | undefined {
  return dispatch.items.find((i) => i.id === itemId)?.material
}

function itemLabel(item: DispatchItem, materials: MaterialOption[]): string {
  return materials.find((m) => m.id === item.material)?.name ?? item.material
}

export default function DeliveryModal({
  open,
  dispatch,
  materials,
  onClose,
  onDelivered,
}: DeliveryModalProps) {
  const [receivedBy, setReceivedBy] = useState('')
  const [signatureRef, setSignatureRef] = useState('')
  const [geoLat, setGeoLat] = useState('')
  const [geoLng, setGeoLng] = useState('')
  const [geoError, setGeoError] = useState<string | null>(null)
  const [discrepancies, setDiscrepancies] = useState<DiscrepancyDraft[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  function captureGps() {
    setGeoError(null)
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGeoError('GPS indisponível — informe as coordenadas manualmente.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeoLat(pos.coords.latitude.toFixed(6))
        setGeoLng(pos.coords.longitude.toFixed(6))
      },
      () => setGeoError('Não foi possível capturar o GPS — informe manualmente.')
    )
  }

  function addDiscrepancy() {
    setDiscrepancies((d) => [
      ...d,
      { type: 'missing', dispatch_item: dispatch.items[0]?.id ?? '', quantity: '1', notes: '' },
    ])
  }

  function updateDiscrepancy(idx: number, patch: Partial<DiscrepancyDraft>) {
    setDiscrepancies((current) => current.map((d, i) => (i === idx ? { ...d, ...patch } : d)))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!receivedBy.trim()) {
      setError('Informe quem recebeu a entrega.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        received_by: receivedBy,
        signature_ref: signatureRef,
        geo_lat: geoLat ? geoLat : null,
        geo_lng: geoLng ? geoLng : null,
        discrepancies: discrepancies.map((d) => ({
          type: d.type,
          dispatch_item: d.dispatch_item,
          material: itemMaterial(dispatch, d.dispatch_item),
          quantity: d.quantity,
          notes: d.notes,
        })),
      }
      const proof = await apiFetch<ProofOfDelivery>(
        `${LOGISTICS_ENDPOINTS.dispatches}${dispatch.id}/deliver/`,
        { method: 'POST', body: JSON.stringify(body) }
      )
      onDelivered(proof)
    } catch {
      setError('Erro ao registrar a entrega.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-xl rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Registrar entrega</h2>
            <p className="font-mono text-xs text-slate-500">{dispatch.manifest_code}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar" className="text-slate-400 hover:text-slate-600">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="space-y-4 px-5 py-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <div>
            <label htmlFor="del-received-by" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Recebido por *
            </label>
            <input
              id="del-received-by"
              type="text"
              value={receivedBy}
              onChange={(e) => setReceivedBy(e.target.value)}
              placeholder="Nome de quem recebeu"
              className={INPUT_CLASS}
            />
          </div>

          <div>
            <label htmlFor="del-signature" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Referência da assinatura (URL/ID)
            </label>
            <input
              id="del-signature"
              type="text"
              value={signatureRef}
              onChange={(e) => setSignatureRef(e.target.value)}
              placeholder="Link ou identificador do comprovante assinado"
              className={INPUT_CLASS}
            />
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-neu-inkSoft">Localização (GPS)</span>
              <button
                type="button"
                onClick={captureGps}
                className="inline-flex items-center gap-1 text-xs font-medium text-neu-brand hover:underline"
              >
                <MapPin size={14} /> Capturar GPS
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label htmlFor="del-lat" className="sr-only">Latitude</label>
                <input
                  id="del-lat"
                  type="number"
                  step="0.000001"
                  value={geoLat}
                  onChange={(e) => setGeoLat(e.target.value)}
                  placeholder="Latitude"
                  className={INPUT_CLASS}
                />
              </div>
              <div>
                <label htmlFor="del-lng" className="sr-only">Longitude</label>
                <input
                  id="del-lng"
                  type="number"
                  step="0.000001"
                  value={geoLng}
                  onChange={(e) => setGeoLng(e.target.value)}
                  placeholder="Longitude"
                  className={INPUT_CLASS}
                />
              </div>
            </div>
            {geoError && <p className="mt-1 text-xs text-yellow-700">{geoError}</p>}
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-neu-inkSoft">Divergências</span>
              <button
                type="button"
                onClick={addDiscrepancy}
                className="inline-flex items-center gap-1 text-xs font-medium text-neu-brand hover:underline"
              >
                <Plus size={14} /> Adicionar divergência
              </button>
            </div>
            {discrepancies.length === 0 && (
              <p className="text-xs text-neu-inkMuted">Nenhuma divergência — entrega conferida.</p>
            )}
            <div className="space-y-2">
              {discrepancies.map((d, idx) => (
                <div key={idx} className="rounded-lg border border-slate-200 p-2">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label htmlFor={`disc-type-${idx}`} className="sr-only">Tipo da divergência {idx + 1}</label>
                      <select
                        id={`disc-type-${idx}`}
                        value={d.type}
                        onChange={(e) => updateDiscrepancy(idx, { type: e.target.value as DiscrepancyType })}
                        className={INPUT_CLASS}
                      >
                        {DISCREPANCY_TYPE_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor={`disc-item-${idx}`} className="sr-only">Item da divergência {idx + 1}</label>
                      <select
                        id={`disc-item-${idx}`}
                        value={d.dispatch_item}
                        onChange={(e) => updateDiscrepancy(idx, { dispatch_item: e.target.value })}
                        className={INPUT_CLASS}
                      >
                        <option value="">Selecionar item</option>
                        {dispatch.items.map((it) => (
                          <option key={it.id} value={it.id}>
                            {itemLabel(it, materials)}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="mt-2 flex gap-2">
                    <label htmlFor={`disc-qty-${idx}`} className="sr-only">Quantidade da divergência {idx + 1}</label>
                    <input
                      id={`disc-qty-${idx}`}
                      type="number"
                      min="0"
                      step="0.001"
                      value={d.quantity}
                      onChange={(e) => updateDiscrepancy(idx, { quantity: e.target.value })}
                      placeholder="Qtd."
                      className={`${INPUT_CLASS} w-24`}
                    />
                    <label htmlFor={`disc-notes-${idx}`} className="sr-only">Observação da divergência {idx + 1}</label>
                    <input
                      id={`disc-notes-${idx}`}
                      type="text"
                      value={d.notes}
                      onChange={(e) => updateDiscrepancy(idx, { notes: e.target.value })}
                      placeholder="Observação"
                      className={`${INPUT_CLASS} flex-1`}
                    />
                    <button
                      type="button"
                      onClick={() => setDiscrepancies((cur) => cur.filter((_, i) => i !== idx))}
                      aria-label={`Remover divergência ${idx + 1}`}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-red-500 hover:bg-red-50"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-app">
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {saving ? 'Registrando...' : 'Confirmar entrega'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
