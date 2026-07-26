'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import {
  LOGISTICS_ENDPOINTS,
  type Dispatch,
  type PickList,
  type WarehouseOption,
} from './logisticsMeta'

interface DispatchFormProps {
  open: boolean
  pickLists: PickList[]
  warehouses: WarehouseOption[]
  onClose: () => void
  onCreated: (dispatch: Dispatch) => void
}

const INPUT_CLASS =
  'w-full rounded-lg border border-slate-200 bg-neu-panel px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500'

function defaultManifest(): string {
  const now = new Date()
  const stamp = now.toISOString().slice(0, 10).replace(/-/g, '')
  const rand = Math.random().toString(36).slice(2, 7).toUpperCase()
  return `MNF-${stamp}-${rand}`
}

export default function DispatchForm({
  open,
  pickLists,
  warehouses,
  onClose,
  onCreated,
}: DispatchFormProps) {
  const [pickList, setPickList] = useState('')
  const [manifestCode, setManifestCode] = useState(defaultManifest)
  const [sourceWarehouse, setSourceWarehouse] = useState('')
  const [destinationWarehouse, setDestinationWarehouse] = useState('')
  const [freightCost, setFreightCost] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  const ready = Boolean(pickList && manifestCode && sourceWarehouse)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!ready) {
      setError('Informe a lista separada, o código do manifesto e o armazém de origem.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        pick_list: pickList,
        manifest_code: manifestCode,
        source_warehouse: sourceWarehouse,
      }
      if (destinationWarehouse) body.destination_warehouse = destinationWarehouse
      if (freightCost) body.freight_cost = freightCost
      const created = await apiFetch<Dispatch>(LOGISTICS_ENDPOINTS.dispatches, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onCreated(created)
    } catch {
      setError('Erro ao criar despacho. O código do manifesto precisa ser único.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">Novo despacho</h2>
          <button type="button" onClick={onClose} aria-label="Fechar" className="text-slate-400 hover:text-slate-600">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="space-y-4 px-5 py-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <div>
            <label htmlFor="disp-picklist" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Lista de separação *
            </label>
            <select
              id="disp-picklist"
              value={pickList}
              onChange={(e) => setPickList(e.target.value)}
              required
              className={INPUT_CLASS}
            >
              <option value="">Selecionar lista separada</option>
              {pickLists.map((pl) => (
                <option key={pl.id} value={pl.id}>
                  {pl.id}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="disp-manifest" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Código do manifesto (QR) *
            </label>
            <input
              id="disp-manifest"
              type="text"
              value={manifestCode}
              onChange={(e) => setManifestCode(e.target.value)}
              className={`${INPUT_CLASS} font-mono`}
            />
            {/* No QR library is bundled — render the manifest payload prominently as the scannable code. */}
            <div className="mt-2 rounded-lg border-2 border-dashed border-slate-300 bg-neu-app px-4 py-3 text-center">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">Manifesto / QR</p>
              <p className="mt-1 break-all font-mono text-sm font-semibold text-neu-ink">{manifestCode || '—'}</p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="disp-source" className="mb-1 block text-xs font-medium text-neu-inkSoft">
                Armazém de origem *
              </label>
              <select
                id="disp-source"
                value={sourceWarehouse}
                onChange={(e) => setSourceWarehouse(e.target.value)}
                required
                className={INPUT_CLASS}
              >
                <option value="">Selecionar</option>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="disp-dest" className="mb-1 block text-xs font-medium text-neu-inkSoft">
                Armazém de destino
              </label>
              <select
                id="disp-dest"
                value={destinationWarehouse}
                onChange={(e) => setDestinationWarehouse(e.target.value)}
                className={INPUT_CLASS}
              >
                <option value="">Definido pela unidade</option>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="disp-freight" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Custo de frete (R$)
            </label>
            <input
              id="disp-freight"
              type="number"
              min="0"
              step="0.01"
              value={freightCost}
              onChange={(e) => setFreightCost(e.target.value)}
              placeholder="0,00"
              className={INPUT_CLASS}
            />
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
              {saving ? 'Criando...' : 'Criar despacho'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
