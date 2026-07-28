import { formatBRL } from './financeFormat'

interface CashFlowSummaryProps {
  /** Realized inflow total (decimal string or number). */
  inflow: number
  /** Realized outflow total. */
  outflow: number
  /** Count of forecast (not yet realized) entries in range. */
  forecastCount: number
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: 'success' | 'critical' | 'neutral' }) {
  const valueClass =
    tone === 'critical' ? 'text-rose-600' : tone === 'success' ? 'text-emerald-600' : 'text-neu-ink'
  return (
    <div className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel">
      <p className="text-xs uppercase tracking-wide text-neu-inkMuted">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
    </div>
  )
}

export default function CashFlowSummary({ inflow, outflow, forecastCount }: CashFlowSummaryProps) {
  const balance = inflow - outflow
  return (
    <div className="grid gap-3 sm:grid-cols-4">
      <Tile label="Entradas realizadas" value={formatBRL(inflow)} tone="success" />
      <Tile label="Saídas realizadas" value={formatBRL(outflow)} tone="critical" />
      <Tile label="Saldo do período" value={formatBRL(balance)} tone={balance < 0 ? 'critical' : 'success'} />
      <Tile label="Lançamentos previstos" value={String(forecastCount)} tone="neutral" />
    </div>
  )
}
