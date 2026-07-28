import SettlementRow, { type Settlement } from './SettlementRow'

// Dense table of professional settlements (repasses). Presentational only —
// data loading, state and the approve/pay lifecycle live in the page.

interface Props {
  settlements: Settlement[]
  onApprove?: (settlement: Settlement) => void
  onPay?: (settlement: Settlement) => void
}

const HEADERS = ['Prestador', 'Competência', 'Bruto', 'Deduções', 'Líquido', 'Status', 'Ações']

export default function SettlementList({ settlements, onApprove, onPay }: Props) {
  return (
    <div className="bg-neu-panel rounded-lg border border-white overflow-x-auto">
      <table className="w-full text-sm min-w-[760px]">
        <thead>
          <tr className="border-b border-white bg-neu-panel">
            {HEADERS.map((h) => (
              <th
                key={h}
                className={`px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted ${
                  ['Bruto', 'Deduções', 'Líquido', 'Ações'].includes(h) ? 'text-right' : 'text-left'
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {settlements.map((settlement) => (
            <SettlementRow
              key={settlement.id}
              settlement={settlement}
              onApprove={onApprove}
              onPay={onPay}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
