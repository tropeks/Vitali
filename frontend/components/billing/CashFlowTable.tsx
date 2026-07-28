import CashFlowStatusBadge from './CashFlowStatusBadge'
import { formatBRL, formatDate, type CashFlowEntry } from './financeFormat'

interface CashFlowTableProps {
  entries: CashFlowEntry[]
}

const HEADERS = ['Descrição', 'Tipo', 'Categoria', 'Valor', 'Vencimento', 'Status']

const KIND_LABEL: Record<string, string> = { inflow: 'Entrada', outflow: 'Saída' }

export default function CashFlowTable({ entries }: CashFlowTableProps) {
  return (
    <div className="bg-neu-panel rounded-lg border border-white overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-white bg-neu-panel">
            {HEADERS.map((h) => (
              <th
                key={h}
                className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className="border-b border-white/60 last:border-0">
              <td className="px-4 py-3 text-neu-ink">{e.description}</td>
              <td className={`px-4 py-3 font-medium ${e.kind === 'inflow' ? 'text-emerald-600' : 'text-rose-600'}`}>
                {KIND_LABEL[e.kind] ?? e.kind}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">{e.category || '—'}</td>
              <td className="px-4 py-3 font-medium text-neu-ink tabular-nums">{formatBRL(e.amount)}</td>
              <td className="px-4 py-3 text-neu-inkSoft tabular-nums">{formatDate(e.due_date)}</td>
              <td className="px-4 py-3"><CashFlowStatusBadge status={e.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
