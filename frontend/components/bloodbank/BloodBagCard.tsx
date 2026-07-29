'use client'

import { Droplet, FlaskConical, Snowflake, Zap } from 'lucide-react'
import {
  aboRhLabel,
  expiryMeta,
  formatDate,
  serologyStatusMeta,
  stockStatusMeta,
  type BloodBagDTO,
} from './bloodbank-types'

interface BloodBagCardProps {
  bag: BloodBagDTO
  canManage: boolean
  /** Registrar triagem sorológica — only offered for quarantined bags. */
  onSerology?: (bag: BloodBagDTO) => void
}

/**
 * One blood bag (bolsa) in the estoque board — DIN, hemocomponente, ABO/Rh
 * badge, volume, validade highlight, serology + stock status pills and the
 * atributo flags. A quarantined bag offers the "Registrar sorologia" action
 * (hemoterapia.manage).
 */
export default function BloodBagCard({ bag, canManage, onSerology }: BloodBagCardProps) {
  const serology = serologyStatusMeta(bag.serology_status)
  const stock = stockStatusMeta(bag.stock_status)
  const expiry = expiryMeta(bag)
  const isQuarantine = bag.serology_status === 'quarentena'

  return (
    <article
      aria-label={`Bolsa ${bag.identifier}`}
      className={`rounded-lg border bg-neu-panel p-3 ${
        expiry.tone === 'expired'
          ? 'border-red-200'
          : expiry.tone === 'soon'
            ? 'border-amber-200'
            : 'border-slate-200'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex min-w-[2.75rem] items-center justify-center gap-0.5 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-sm font-bold text-red-700">
            <Droplet size={13} aria-hidden />
            {aboRhLabel(bag.abo, bag.rh_factor)}
          </span>
          <div>
            <p className="font-mono text-xs text-neu-inkMuted">{bag.identifier}</p>
            <p className="text-sm font-semibold text-neu-ink">
              {bag.component_display ?? bag.component_code ?? 'Hemocomponente'}
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${stock.badgeClass}`}
          >
            {stock.label}
          </span>
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${serology.badgeClass}`}
          >
            {serology.label}
          </span>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neu-inkMuted">
        <span>{bag.volume_ml} mL</span>
        <span>Coleta {formatDate(bag.collection_date)}</span>
        <span className={expiry.className}>{expiry.label}</span>
      </div>

      {(bag.irradiada || bag.leucodepletada || bag.aferese) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {bag.irradiada && (
            <span className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700">
              <Zap size={10} aria-hidden />
              Irradiada
            </span>
          )}
          {bag.leucodepletada && (
            <span className="inline-flex items-center gap-1 rounded border border-sky-200 bg-sky-50 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700">
              <Snowflake size={10} aria-hidden />
              Leucodepletada
            </span>
          )}
          {bag.aferese && (
            <span className="inline-flex items-center rounded border border-teal-200 bg-teal-50 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700">
              Aférese
            </span>
          )}
        </div>
      )}

      {canManage && isQuarantine && onSerology && (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <button
            type="button"
            onClick={() => onSerology(bag)}
            className="inline-flex items-center gap-1.5 rounded-md border border-neu-brand px-2.5 py-1 text-xs font-semibold text-neu-brand hover:bg-blue-50"
          >
            <FlaskConical size={13} aria-hidden />
            Registrar sorologia
          </button>
        </div>
      )}
    </article>
  )
}
