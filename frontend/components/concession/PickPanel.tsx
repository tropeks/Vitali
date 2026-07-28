'use client'

import { useState } from 'react'
import { apiFetch } from '@/lib/api'
import { StatusBadge } from '@/components/shared'
import {
  LOGISTICS_ENDPOINTS,
  PICKLIST_STATUS_META,
  metaOr,
  materialName,
  stockLabel,
  formatQty,
  type PickList,
  type PickItem,
  type MaterialOption,
  type StockItemOption,
  type WarehouseOption,
} from './logisticsMeta'

interface PickPanelProps {
  pickList: PickList
  materials: MaterialOption[]
  stockItems: StockItemOption[]
  warehouses: WarehouseOption[]
  onPicked: (updated: PickList) => void
}

const INPUT_CLASS =
  'rounded-lg border border-slate-200 bg-neu-panel px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500'

interface RowState {
  source_stock_item: string
  picked_qty: string
}

export default function PickPanel({
  pickList,
  materials,
  stockItems,
  warehouses,
  onPicked,
}: PickPanelProps) {
  const [rows, setRows] = useState<Record<string, RowState>>({})
  const [busyItem, setBusyItem] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function rowFor(item: PickItem): RowState {
    return rows[item.id] ?? { source_stock_item: '', picked_qty: String(item.quantity ?? '') }
  }

  function setRow(itemId: string, patch: Partial<RowState>) {
    setRows((current) => ({
      ...current,
      [itemId]: { ...(current[itemId] ?? { source_stock_item: '', picked_qty: '' }), ...patch },
    }))
  }

  async function pick(item: PickItem) {
    const row = rowFor(item)
    if (!row.source_stock_item || !(Number(row.picked_qty) > 0)) {
      setError('Selecione o estoque de origem e informe a quantidade separada.')
      return
    }
    setBusyItem(item.id)
    setError(null)
    try {
      const updated = await apiFetch<PickList>(`${LOGISTICS_ENDPOINTS.pickLists}${pickList.id}/pick/`, {
        method: 'POST',
        body: JSON.stringify({
          pick_item: item.id,
          source_stock_item: row.source_stock_item,
          picked_qty: row.picked_qty,
        }),
      })
      onPicked(updated)
    } catch {
      setError('Erro ao registrar separação.')
    } finally {
      setBusyItem(null)
    }
  }

  return (
    <div className="rounded-lg border border-white bg-neu-panel">
      <div className="flex flex-wrap items-center gap-3 border-b border-white px-4 py-3">
        <h3 className="text-sm font-semibold text-neu-ink">Separação da lista</h3>
        <StatusBadge meta={metaOr(PICKLIST_STATUS_META, pickList.status)} />
        <span className="font-mono text-xs text-neu-inkMuted">{pickList.id}</span>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="divide-y divide-white">
        {pickList.items.map((item) => {
          const row = rowFor(item)
          const options = stockItems.filter((s) => s.material === item.material)
          return (
            <div key={item.id} className="grid gap-3 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_110px_120px] lg:items-end">
              <div className="min-w-0">
                <p className="text-sm font-medium text-neu-ink">{materialName(item.material, materials)}</p>
                <p className="text-xs text-neu-inkMuted">
                  Solicitado {formatQty(item.quantity)}
                  {item.is_picked && ` · separado ${formatQty(item.picked_qty)}`}
                </p>
              </div>
              <div className="min-w-0">
                <label htmlFor={`pick-stock-${item.id}`} className="mb-1 block text-xs font-medium text-neu-inkSoft lg:hidden">
                  Estoque de origem
                </label>
                <select
                  id={`pick-stock-${item.id}`}
                  value={row.source_stock_item}
                  disabled={item.is_picked}
                  onChange={(e) => setRow(item.id, { source_stock_item: e.target.value })}
                  className={`${INPUT_CLASS} w-full`}
                >
                  <option value="">Selecionar estoque</option>
                  {options.map((s) => (
                    <option key={s.id} value={s.id}>
                      {stockLabel(s, warehouses)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor={`pick-qty-${item.id}`} className="mb-1 block text-xs font-medium text-neu-inkSoft lg:hidden">
                  Qtd. separada
                </label>
                <input
                  id={`pick-qty-${item.id}`}
                  type="number"
                  min="0"
                  step="0.001"
                  value={row.picked_qty}
                  disabled={item.is_picked}
                  onChange={(e) => setRow(item.id, { picked_qty: e.target.value })}
                  className={`${INPUT_CLASS} w-full`}
                />
              </div>
              <div className="flex justify-end">
                {item.is_picked ? (
                  <span className="inline-flex rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700">
                    Separado
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={busyItem === item.id}
                    onClick={() => pick(item)}
                    className="rounded-lg bg-neu-brand px-3 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {busyItem === item.id ? 'Separando...' : 'Separar'}
                  </button>
                )}
              </div>
            </div>
          )
        })}
        {pickList.items.length === 0 && (
          <p className="px-4 py-3 text-sm text-neu-inkMuted">Nenhum item nesta lista de separação.</p>
        )}
      </div>
    </div>
  )
}
