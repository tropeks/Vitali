'use client'

import { useState } from 'react'
import { SectionState } from '@/components/shared'
import ReconciliarAihModal from './ReconciliarAihModal'
import RejeitarAihModal from './RejeitarAihModal'
import { autorizacaoSituacaoMeta, formatBRL, type AihAutorizacaoLine } from './sus-types'

interface Props {
  aihs: AihAutorizacaoLine[]
  /** `sus.write` — gates reconciliar/rejeitar. */
  canWrite: boolean
  /** Reload the parent's data after a reconcile/reject. */
  onChanged: () => void
}

/**
 * Lista de autorizações AIH (faturamento SUS de internação). Read-only: a AIH
 * nasce do bridge Admission→AIH (não há criação manual aqui). Cada linha mostra
 * a situação (badge) e — com `sus.write` — as ações Reconciliar (número oficial
 * do gestor) e Rejeitar (glosa). A lista vem do detalhe da competência.
 */
export default function AihList({ aihs, canWrite, onChanged }: Props) {
  const [reconcileFor, setReconcileFor] = useState<AihAutorizacaoLine | null>(null)
  const [rejectFor, setRejectFor] = useState<AihAutorizacaoLine | null>(null)

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-neu-ink">AIH — internação ({aihs.length})</h2>

      {aihs.length === 0 ? (
        <SectionState
          title="Nenhuma AIH"
          detail="Não há autorizações AIH nesta competência. A AIH é gerada a partir de uma internação com alta."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-neu-panel">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100">
              <tr>
                {['Número', 'Situação', 'Internação', 'CID', 'Valor', 'Ações'].map((header) => (
                  <th
                    key={header}
                    className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {aihs.map((aih) => {
                const meta = autorizacaoSituacaoMeta(aih.situacao)
                const canReconcile = canWrite && aih.situacao !== 'autorizada'
                const canReject = canWrite && aih.situacao !== 'rejeitada'
                return (
                  <tr key={aih.id}>
                    <td className="px-4 py-3 font-mono text-neu-ink">{aih.numero_aih}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}
                      >
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-neu-inkSoft">
                      {aih.data_internacao} → {aih.data_saida || '—'}
                    </td>
                    <td className="px-4 py-3 text-neu-inkSoft">{aih.cid_principal || '—'}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{formatBRL(aih.valor)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {canReconcile && (
                          <button
                            type="button"
                            onClick={() => setReconcileFor(aih)}
                            className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                          >
                            Reconciliar
                          </button>
                        )}
                        {canReject && (
                          <button
                            type="button"
                            onClick={() => setRejectFor(aih)}
                            className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-100"
                          >
                            Rejeitar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {reconcileFor && (
        <ReconciliarAihModal
          aihId={reconcileFor.id}
          numeroAtual={reconcileFor.numero_aih}
          onClose={() => setReconcileFor(null)}
          onReconciled={() => {
            setReconcileFor(null)
            onChanged()
          }}
        />
      )}
      {rejectFor && (
        <RejeitarAihModal
          aihId={rejectFor.id}
          numeroAtual={rejectFor.numero_aih}
          onClose={() => setRejectFor(null)}
          onRejected={() => {
            setRejectFor(null)
            onChanged()
          }}
        />
      )}
    </section>
  )
}
