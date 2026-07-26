'use client'

import { StatusBadge } from '@/components/shared'
import {
  DISCREPANCY_TYPE_META,
  metaOr,
  materialName,
  formatQty,
  formatDateTime,
  type ProofOfDelivery,
  type Dispatch,
  type DispatchDiscrepancy,
  type MaterialOption,
} from './logisticsMeta'

interface PodViewerProps {
  proofs: ProofOfDelivery[]
  dispatches: Dispatch[]
  discrepancies: DispatchDiscrepancy[]
  materials: MaterialOption[]
}

function manifestFor(dispatchId: string, dispatches: Dispatch[]): string {
  return dispatches.find((d) => d.id === dispatchId)?.manifest_code ?? dispatchId
}

export default function PodViewer({ proofs, dispatches, discrepancies, materials }: PodViewerProps) {
  return (
    <div className="grid gap-3">
      {proofs.map((pod) => {
        const podDiscrepancies = discrepancies.filter((d) => d.dispatch === pod.dispatch)
        return (
          <div key={pod.id} className="rounded-lg border border-white bg-neu-panel p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">Manifesto</p>
                <p className="font-mono text-sm font-semibold text-neu-ink">
                  {manifestFor(pod.dispatch, dispatches)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">Entregue em</p>
                <p className="text-sm text-neu-ink tabular-nums">{formatDateTime(pod.delivered_at)}</p>
              </div>
            </div>

            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">Recebido por</dt>
                <dd className="text-sm text-neu-ink">{pod.received_by}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">Assinatura</dt>
                <dd className="break-all text-sm text-neu-ink">{pod.signature_ref || '—'}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">GPS</dt>
                <dd className="font-mono text-sm text-neu-ink">
                  {pod.geo_lat != null && pod.geo_lng != null ? `${pod.geo_lat}, ${pod.geo_lng}` : '—'}
                </dd>
              </div>
            </dl>

            {podDiscrepancies.length > 0 && (
              <div className="mt-3 border-t border-white pt-3">
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-neu-inkMuted">
                  Divergências ({podDiscrepancies.length})
                </p>
                <ul className="space-y-1">
                  {podDiscrepancies.map((d) => (
                    <li key={d.id} className="flex items-center gap-2 text-sm">
                      <StatusBadge meta={metaOr(DISCREPANCY_TYPE_META, d.type)} />
                      <span className="text-neu-ink">{materialName(d.material, materials)}</span>
                      <span className="text-neu-inkMuted">· {formatQty(d.quantity)}</span>
                      {d.notes && <span className="text-neu-inkMuted">— {d.notes}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
