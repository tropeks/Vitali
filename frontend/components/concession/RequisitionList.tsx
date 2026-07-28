'use client'

import { StatusBadge } from '@/components/shared'
import {
  REQUISITION_STATUS_META,
  metaOr,
  nameFrom,
  materialName,
  formatQty,
  formatDateTime,
  type SupplyRequisition,
  type FacilityOption,
  type MaterialOption,
} from './logisticsMeta'

export type RequisitionAction = 'submit' | 'approve' | 'cancel' | 'createPick'

interface RequisitionListProps {
  requisitions: SupplyRequisition[]
  facilities: FacilityOption[]
  materials: MaterialOption[]
  busyId: string | null
  onAction: (requisition: SupplyRequisition, action: RequisitionAction) => void
}

const ACTION_LABEL: Record<RequisitionAction, string> = {
  submit: 'Enviar',
  approve: 'Aprovar',
  cancel: 'Cancelar',
  createPick: 'Criar separação',
}

function actionsFor(status: SupplyRequisition['status']): RequisitionAction[] {
  switch (status) {
    case 'draft':
      return ['submit', 'cancel']
    case 'submitted':
      return ['approve', 'cancel']
    case 'approved':
      return ['createPick', 'cancel']
    default:
      return []
  }
}

export default function RequisitionList({
  requisitions,
  facilities,
  materials,
  busyId,
  onAction,
}: RequisitionListProps) {
  return (
    <div className="bg-neu-panel rounded-lg border border-white overflow-x-auto">
      <table className="w-full text-sm min-w-[820px]">
        <thead>
          <tr className="border-b border-white bg-neu-panel">
            {['Unidade', 'Itens', 'Status', 'Criada em', 'Ações'].map((h) => (
              <th key={h} className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {requisitions.map((req) => {
            const actions = actionsFor(req.status)
            const busy = busyId === req.id
            return (
              <tr key={req.id} className="border-b border-white align-top hover:bg-neu-panelAlt">
                <td className="px-4 py-3 font-medium text-neu-ink">
                  {nameFrom(req.requesting_facility, facilities)}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  <ul className="space-y-0.5">
                    {req.items.map((it, i) => (
                      <li key={it.id ?? i}>
                        {materialName(it.material, materials)} · {formatQty(it.quantity)}
                      </li>
                    ))}
                    {req.items.length === 0 && <li className="text-neu-inkMuted">—</li>}
                  </ul>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge meta={metaOr(REQUISITION_STATUS_META, req.status)} />
                </td>
                <td className="px-4 py-3 text-neu-inkSoft tabular-nums">{formatDateTime(req.created_at)}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-2 justify-end">
                    {actions.length === 0 && <span className="text-xs text-neu-inkMuted">—</span>}
                    {actions.map((a) => (
                      <button
                        key={a}
                        type="button"
                        disabled={busy}
                        onClick={() => onAction(req, a)}
                        className={`text-xs font-medium hover:underline disabled:opacity-40 ${
                          a === 'cancel' ? 'text-red-600' : 'text-neu-brand'
                        }`}
                      >
                        {ACTION_LABEL[a]}
                      </button>
                    ))}
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
