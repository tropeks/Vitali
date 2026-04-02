'use client';

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface Bucket {
  period: string;
  billed: string;
  collected: string;
  denied: string;
}

interface Props {
  data: Bucket[];
}

function fmt(val: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }).format(val);
}

export default function RevenueChart({ data }: Props) {
  const chartData = data.map(b => {
    const billed = Number(b.billed);
    const denied = Number(b.denied);
    return {
      period: b.period,
      nao_glosado: Math.max(0, billed - denied),
      glosado: denied,
    };
  });

  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="period"
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          tickFormatter={v => `R$${(v / 1000).toFixed(0)}k`}
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip formatter={(val: number) => fmt(val)} />
        <Legend
          iconType="square"
          formatter={name => name === 'nao_glosado' ? 'Não Glosado' : 'Glosado'}
        />
        <Area
          type="monotone"
          dataKey="nao_glosado"
          stackId="1"
          stroke="#22c55e"
          fill="#dcfce7"
          name="nao_glosado"
        />
        <Area
          type="monotone"
          dataKey="glosado"
          stackId="1"
          stroke="#ef4444"
          fill="#fee2e2"
          name="glosado"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
