'use client'

import { formatBRL, formatInt, type PnlByServiceLine } from './pnlMeta'

/**
 * PnlServiceTable — per-service profitability breakdown. Columns: serviço,
 * volume de exames, receita, custo de consumo, and the resulting margin.
 */

interface Props {
  rows: PnlByServiceLine[]
}

export default function PnlServiceTable({ rows }: Props) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
            <th className="px-4 py-2">Serviço</th>
            <th className="px-4 py-2 text-right">Exames</th>
            <th className="px-4 py-2 text-right">Receita</th>
            <th className="px-4 py-2 text-right">Custo de consumo</th>
            <th className="px-4 py-2 text-right">Margem</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => {
            const margin = Number(r.revenue) - Number(r.consumption_cost)
            return (
              <tr key={`${r.service}-${r.service_code}`} className="text-slate-700">
                <td className="px-4 py-2">
                  <span className="font-medium text-slate-900">{r.service_name}</span>
                  <span className="ml-2 text-xs text-slate-400">{r.service_code}</span>
                </td>
                <td className="px-4 py-2 text-right tabular-nums">{formatInt(r.exam_volume)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{formatBRL(r.revenue)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{formatBRL(r.consumption_cost)}</td>
                <td
                  className={`px-4 py-2 text-right tabular-nums font-medium ${
                    margin < 0 ? 'text-red-600' : 'text-green-700'
                  }`}
                >
                  {formatBRL(margin)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
