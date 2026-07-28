'use client'

import { Activity } from 'lucide-react'
import { StatusBadge, SectionState } from '@/components/shared'
import {
  acuityMeta,
  formatDateTime,
  type RiskClassification,
} from './emergency-chart-types'

interface Props {
  /** Append-only triagem history, already newest-first (API ordering). */
  classifications: RiskClassification[]
}

/**
 * Histórico de classificações de risco (E5) — the append-only Manchester triagem
 * timeline of a boletim. Each entry is a NEW row (re-triagem never edits), so the
 * audit trail of every priority the patient held is preserved. Rendered
 * newest-first: the top entry is the current acuity.
 */
export default function EmergencyClassificationHistory({ classifications }: Props) {
  if (classifications.length === 0) {
    return (
      <SectionState
        title="Sem classificação de risco"
        detail="Nenhuma triagem Manchester foi registrada para este boletim."
      />
    )
  }

  return (
    <ol className="space-y-2" aria-label="Histórico de classificações de risco">
      {classifications.map((classification, index) => {
        const meta = acuityMeta(classification.acuity_level)
        return (
          <li
            key={classification.id}
            className="rounded-lg border border-slate-200 bg-white px-4 py-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Activity size={15} className="shrink-0 text-slate-400" />
                <StatusBadge meta={meta} />
                {index === 0 && (
                  <span className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                    Atual
                  </span>
                )}
              </div>
              <span className="text-xs text-slate-500">
                Tempo-alvo {classification.target_minutes} min
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-700">
              {classification.flowchart_code || 'Fluxograma'} ·{' '}
              {classification.discriminator_code || 'Discriminador'}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              {formatDateTime(classification.classified_at)}
            </p>
            {classification.notes && (
              <p className="mt-1 text-xs text-slate-600">{classification.notes}</p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
