'use client'

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { formatBRL, type PnlCostBreakdown } from './pnlMeta'

/**
 * PnlCostBreakdownChart — donut of the three P&L cost legs (consumo, frete,
 * manutenção). Values arrive as JSON numbers from the raw P&L roll-up.
 */

interface Props {
  breakdown: PnlCostBreakdown
}

const SLICE = [
  { key: 'consumption', label: 'Consumo', color: '#3b82f6' },
  { key: 'freight', label: 'Frete', color: '#f59e0b' },
  { key: 'maintenance', label: 'Manutenção', color: '#8b5cf6' },
] as const

export default function PnlCostBreakdownChart({ breakdown }: Props) {
  const data = SLICE.map((s) => ({
    name: s.label,
    value: Math.max(0, Number(breakdown[s.key]) || 0),
    color: s.color,
  }))
  const total = data.reduce((acc, d) => acc + d.value, 0)

  if (total <= 0) {
    return (
      <p className="py-8 text-center text-sm text-neu-inkMuted">
        Sem custos no período.
      </p>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={55}
          outerRadius={90}
          paddingAngle={2}
        >
          {data.map((d) => (
            <Cell key={d.name} fill={d.color} />
          ))}
        </Pie>
        <Tooltip formatter={(val: number) => formatBRL(val)} />
        <Legend iconType="square" />
      </PieChart>
    </ResponsiveContainer>
  )
}
