import PayableStatusBadge from './PayableStatusBadge'
import { formatBRL, formatDate, type Payable } from './financeFormat'

interface PayableTableProps {
  payables: Payable[]
  /** Maker-checker: planned → approved (approver must differ from creator). */
  onApprove: (payable: Payable) => void
  /** approved → paid. */
  onPay: (payable: Payable) => void
  /** id currently mutating — disables its action buttons. */
  busyId?: string | null
}

const HEADERS = ['Descrição', 'Categoria', 'Valor', 'Vencimento', 'Status', 'Ações']

export default function PayableTable({ payables, onApprove, onPay, busyId }: PayableTableProps) {
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
          {payables.map((p) => (
            <tr key={p.id} className="border-b border-white/60 last:border-0">
              <td className="px-4 py-3 text-neu-ink">{p.description}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{p.category || '—'}</td>
              <td className="px-4 py-3 font-medium text-neu-ink tabular-nums">{formatBRL(p.amount)}</td>
              <td className="px-4 py-3 text-neu-inkSoft tabular-nums">{formatDate(p.due_date)}</td>
              <td className="px-4 py-3"><PayableStatusBadge status={p.status} /></td>
              <td className="px-4 py-3">
                {p.status === 'planned' && (
                  <button
                    className="neu-button-secondary"
                    disabled={busyId === p.id}
                    onClick={() => onApprove(p)}
                  >
                    {busyId === p.id ? 'Aprovando…' : 'Aprovar'}
                  </button>
                )}
                {p.status === 'approved' && (
                  <button
                    className="neu-button-primary"
                    disabled={busyId === p.id}
                    onClick={() => onPay(p)}
                  >
                    {busyId === p.id ? 'Pagando…' : 'Pagar'}
                  </button>
                )}
                {(p.status === 'paid' || p.status === 'cancelled') && (
                  <span className="text-xs text-neu-inkMuted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
