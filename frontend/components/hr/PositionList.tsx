'use client'

import type { Position } from '@/app/(dashboard)/rh/cargos/page'
import { StatusBadge } from '@/components/shared'
import { getActivenessMeta } from '@/lib/operational-ui'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PositionListProps {
  positions: Position[]
  onEdit: (position: Position) => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PositionList({ positions, onEdit }: PositionListProps) {
  return (
    <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[560px]">
        <thead>
          <tr className="border-b border-slate-100 bg-neu-panel">
            {['Título', 'CBO', 'Status', 'Ações'].map((h) => (
              <th
                key={h}
                className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {positions.map((position) => (
            <tr key={position.id} className="hover:bg-neu-panelAlt transition-colors">
              <td className="px-4 py-3 font-medium text-neu-ink">{position.title}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{position.cbo || '—'}</td>
              <td className="px-4 py-3">
                <StatusBadge meta={getActivenessMeta(position.active)} />
              </td>
              <td className="px-4 py-3">
                <button
                  onClick={() => onEdit(position)}
                  className="text-neu-brand hover:underline text-xs font-semibold"
                >
                  Editar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
