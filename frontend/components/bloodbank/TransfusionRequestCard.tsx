'use client'

import { CheckCircle2, Droplet, ShieldCheck, ShieldX } from 'lucide-react'
import {
  canCancel,
  canLiberar,
  canReserve,
  requestStatusMeta,
  urgenciaMeta,
  type CrossMatchDTO,
  type TransfusionRequestDTO,
} from './bloodbank-types'

interface TransfusionRequestCardProps {
  request: TransfusionRequestDTO
  canManage: boolean
  onReserve: (request: TransfusionRequestDTO) => void
  onLiberar: (request: TransfusionRequestDTO) => void
  onCancel: (request: TransfusionRequestDTO) => void
}

function CrossMatchRow({ crossmatch }: { crossmatch: CrossMatchDTO }) {
  const ok = crossmatch.compativel
  return (
    <div
      className={`flex flex-wrap items-center gap-2 rounded-md border px-2 py-1.5 text-[11px] ${
        ok ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-700'
      }`}
    >
      {ok ? <ShieldCheck size={13} aria-hidden /> : <ShieldX size={13} aria-hidden />}
      <span className="font-semibold">
        Prova cruzada: {ok ? 'compatível' : 'incompatível'}
      </span>
      {crossmatch.bag_identifier && (
        <span className="font-mono text-neu-inkMuted">Bolsa {crossmatch.bag_identifier}</span>
      )}
      <span>ABO {crossmatch.abo_compativel ? '✓' : '✗'}</span>
      <span>Rh {crossmatch.rh_compativel ? '✓' : '✗'}</span>
    </div>
  )
}

/**
 * One requisição transfusional in the fila — hemocomponente, quantidade,
 * urgência, situação, indicação. When reservada it shows the crossmatch
 * (ABO/Rh/resultado). Agency actions (Reservar / Liberar / Cancelar) are gated
 * by `canManage` and the request status.
 */
export default function TransfusionRequestCard({
  request,
  canManage,
  onReserve,
  onLiberar,
  onCancel,
}: TransfusionRequestCardProps) {
  const status = requestStatusMeta(request.status)
  const urg = urgenciaMeta(request.urgencia)

  return (
    <article
      aria-label={`Requisição ${request.id}`}
      className={`rounded-lg border bg-neu-panel p-3 ${
        urg.accent ? 'border-l-4 border-l-orange-400 border-slate-200' : 'border-slate-200'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Droplet size={16} className="text-red-500" aria-hidden />
          <div>
            <p className="text-sm font-semibold text-neu-ink">
              {request.component_display ?? request.component_code ?? 'Hemocomponente'}
            </p>
            <p className="text-xs text-neu-inkMuted">
              {request.quantidade} unidade{request.quantidade === 1 ? '' : 's'}
              {request.cid ? ` · CID ${request.cid}` : ''}
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${status.badgeClass}`}
          >
            {status.label}
          </span>
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${urg.badgeClass}`}
          >
            {urg.label}
          </span>
        </div>
      </div>

      {request.indicacao && (
        <p className="mt-2 line-clamp-2 text-xs text-neu-inkSoft">{request.indicacao}</p>
      )}

      {request.crossmatches.length > 0 && (
        <div className="mt-2 space-y-1">
          {request.crossmatches.map((xm) => (
            <CrossMatchRow key={xm.id} crossmatch={xm} />
          ))}
        </div>
      )}

      {canManage &&
        (canReserve(request.status) ||
          canLiberar(request.status) ||
          canCancel(request.status)) && (
          <div className="mt-2 flex flex-wrap gap-2 border-t border-slate-100 pt-2">
            {canReserve(request.status) && (
              <button
                type="button"
                onClick={() => onReserve(request)}
                className="inline-flex items-center gap-1.5 rounded-md bg-neu-brand px-2.5 py-1 text-xs font-semibold text-white hover:opacity-90"
              >
                <CheckCircle2 size={13} aria-hidden />
                Reservar
              </button>
            )}
            {canLiberar(request.status) && (
              <button
                type="button"
                onClick={() => onLiberar(request)}
                className="inline-flex items-center gap-1.5 rounded-md border border-neu-brand px-2.5 py-1 text-xs font-semibold text-neu-brand hover:bg-blue-50"
              >
                Liberar
              </button>
            )}
            {canCancel(request.status) && (
              <button
                type="button"
                onClick={() => onCancel(request)}
                className="inline-flex items-center gap-1.5 rounded-md border border-red-200 px-2.5 py-1 text-xs font-semibold text-red-600 hover:bg-red-50"
              >
                Cancelar
              </button>
            )}
          </div>
        )}
    </article>
  )
}
