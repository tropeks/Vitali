'use client'

import { StatusBadge } from '@/components/shared'
import {
  DISPATCH_STATUS_META,
  metaOr,
  nameFrom,
  formatDateTime,
  type Dispatch,
  type WarehouseOption,
} from './logisticsMeta'

interface DispatchListProps {
  dispatches: Dispatch[]
  warehouses: WarehouseOption[]
  busyId: string | null
  onShip: (dispatch: Dispatch) => void
  onDeliver: (dispatch: Dispatch) => void
}

export default function DispatchList({
  dispatches,
  warehouses,
  busyId,
  onShip,
  onDeliver,
}: DispatchListProps) {
  return (
    <div className="bg-neu-panel rounded-lg border border-white overflow-x-auto">
      <table className="w-full text-sm min-w-[860px]">
        <thead>
          <tr className="border-b border-white bg-neu-panel">
            {['Manifesto (QR)', 'Origem', 'Destino', 'Status', 'Enviado', 'Ações'].map((h) => (
              <th key={h} className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dispatches.map((d) => {
            const busy = busyId === d.id
            return (
              <tr key={d.id} className="border-b border-white hover:bg-neu-panelAlt">
                <td className="px-4 py-3">
                  <span className="inline-block rounded border border-slate-300 bg-neu-app px-2 py-1 font-mono text-xs font-semibold text-neu-ink">
                    {d.manifest_code}
                  </span>
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">{nameFrom(d.source_warehouse, warehouses)}</td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  {nameFrom(d.destination_warehouse, warehouses, 'Unidade')}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge meta={metaOr(DISPATCH_STATUS_META, d.status)} />
                </td>
                <td className="px-4 py-3 text-neu-inkSoft tabular-nums">{formatDateTime(d.shipped_at)}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-2 justify-end">
                    {d.status === 'pending' && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onShip(d)}
                        className="text-xs font-medium text-neu-brand hover:underline disabled:opacity-40"
                      >
                        Enviar (baixa de estoque)
                      </button>
                    )}
                    {d.status === 'in_transit' && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onDeliver(d)}
                        className="text-xs font-medium text-neu-brand hover:underline disabled:opacity-40"
                      >
                        Registrar entrega
                      </button>
                    )}
                    {d.status === 'delivered' && <span className="text-xs text-neu-inkMuted">—</span>}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
