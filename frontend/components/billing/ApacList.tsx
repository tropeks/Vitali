'use client'

import { useState } from 'react'
import { FilePlus2 } from 'lucide-react'
import { SectionState } from '@/components/shared'
import ApacForm from './ApacForm'
import { formatBRL, type ApacAutorizacaoLine } from './sus-types'

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
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-neu-panel">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100">
              <tr>
                {['Número', 'Validade', 'CID', 'Valor'].map((header) => (
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
              {apacs.map((apac) => (
                <tr key={apac.id}>
                  <td className="px-4 py-3 font-mono text-neu-ink">{apac.numero_apac}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {apac.validade_inicio} → {apac.validade_fim}
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">{apac.cid_principal || '—'}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">{formatBRL(apac.valor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
