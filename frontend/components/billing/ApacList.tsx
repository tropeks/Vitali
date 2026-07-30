'use client'

import { useState } from 'react'
import { FilePlus2 } from 'lucide-react'
import { SectionState } from '@/components/shared'
import ApacForm from './ApacForm'
import ReconciliarApacModal from './ReconciliarApacModal'
import RejeitarApacModal from './RejeitarApacModal'
import { autorizacaoSituacaoMeta, formatBRL, type ApacAutorizacaoLine } from './sus-types'

interface Props {
  competenciaId: number
  apacs: ApacAutorizacaoLine[]
  /** `sus.write` — gates "Nova APAC". */
  canWrite: boolean
  /** APACs can only be created while the competência is aberta. */
  aberta: boolean
  /** Reload the parent's data after a create. */
  onChanged: () => void
}

/**
 * Lista de autorizações APAC da competência + criação (gated `sus.write`,
 * apenas com a competência aberta). A lista é fornecida pelo detalhe (fonte
 * única); criar dispara `onChanged` para o detalhe recarregar KPIs + listas.
 */
export default function ApacList({ competenciaId, apacs, canWrite, aberta, onChanged }: Props) {
  const [formOpen, setFormOpen] = useState(false)
  const [reconcileFor, setReconcileFor] = useState<ApacAutorizacaoLine | null>(null)
  const [rejectFor, setRejectFor] = useState<ApacAutorizacaoLine | null>(null)

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-neu-ink">APAC ({apacs.length})</h2>
        {canWrite && aberta && !formOpen && (
          <button
            type="button"
            onClick={() => setFormOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-semibold text-blue-700 hover:bg-blue-100"
          >
            <FilePlus2 size={15} />
            Nova APAC
          </button>
        )}
      </div>

      {formOpen && (
        <ApacForm
          competenciaId={competenciaId}
          onCreated={() => {
            setFormOpen(false)
            onChanged()
          }}
          onCancel={() => setFormOpen(false)}
        />
      )}

      {apacs.length === 0 ? (
        <SectionState
          title="Nenhuma APAC"
          detail="Não há autorizações APAC registradas nesta competência."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-neu-panel">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100">
              <tr>
                {['Número', 'Situação', 'Validade', 'CID', 'Valor', 'Ações'].map((header) => (
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
              {apacs.map((apac) => {
                const meta = autorizacaoSituacaoMeta(apac.situacao)
                const canReconcile = canWrite && apac.situacao !== 'autorizada'
                const canReject = canWrite && apac.situacao !== 'rejeitada'
                return (
                  <tr key={apac.id}>
                    <td className="px-4 py-3 font-mono text-neu-ink">{apac.numero_apac}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}
                      >
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-neu-inkSoft">
                      {apac.validade_inicio} → {apac.validade_fim}
                    </td>
                    <td className="px-4 py-3 text-neu-inkSoft">{apac.cid_principal || '—'}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{formatBRL(apac.valor)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {canReconcile && (
                          <button
                            type="button"
                            onClick={() => setReconcileFor(apac)}
                            className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                          >
                            Reconciliar
                          </button>
                        )}
                        {canReject && (
                          <button
                            type="button"
                            onClick={() => setRejectFor(apac)}
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
        <ReconciliarApacModal
          apacId={reconcileFor.id}
          numeroAtual={reconcileFor.numero_apac}
          onClose={() => setReconcileFor(null)}
          onReconciled={() => {
            setReconcileFor(null)
            onChanged()
          }}
        />
      )}
      {rejectFor && (
        <RejeitarApacModal
          apacId={rejectFor.id}
          numeroAtual={rejectFor.numero_apac}
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
