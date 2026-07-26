import ReceivableStatusBadge from './ReceivableStatusBadge'
import { formatBRL, formatDate, type Receivable } from './financeFormat'

interface ReceivableTableProps {
  receivables: Receivable[]
  /** Baixa: POST mark_received/ → status 'received'. */
  onMarkReceived: (receivable: Receivable) => void
  /** id currently mutating — disables its action button. */
  busyId?: string | null
}

const HEADERS = ['Pagador', 'Convênio', 'Valor', 'Vencimento', 'Status', 'Ações']

export default function ReceivableTable({ receivables, onMarkReceived, busyId }: ReceivableTableProps) {
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
          {receivables.map((r) => (
            <tr key={r.id} className="border-b border-white/60 last:border-0">
              <td className="px-4 py-3 text-neu-ink">{r.patient_name || '—'}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{r.provider_name || '—'}</td>
              <td className="px-4 py-3 font-medium text-neu-ink tabular-nums">{formatBRL(r.amount)}</td>
              <td className="px-4 py-3 text-neu-inkSoft tabular-nums">{formatDate(r.due_date)}</td>
              <td className="px-4 py-3"><ReceivableStatusBadge status={r.status} /></td>
              <td className="px-4 py-3">
                {r.status !== 'received' ? (
                  <button
                    className="neu-button-secondary"
                    disabled={busyId === r.id}
                    onClick={() => onMarkReceived(r)}
                  >
                    {busyId === r.id ? 'Baixando…' : 'Dar baixa'}
                  </button>
                ) : (
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
