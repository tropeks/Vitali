'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface Bucket {
  period: string;
  created_count: number;
  closed_count: number;
}

interface Props {
  data: Bucket[];
}

export default function BatchThroughputChart({ data }: Props) {
  if (data.every(b => b.created_count === 0 && b.closed_count === 0)) {
    return (
      <p className="text-sm text-gray-400 text-center py-6">Sem dados para o período</p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="period"
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          allowDecimals={false}
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip />
        <Legend formatter={name => name === 'created_count' ? 'Criados' : 'Fechados'} />
        <Line
          type="monotone"
          dataKey="created_count"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={{ r: 3 }}
          name="created_count"
        />
        <Line
          type="monotone"
          dataKey="closed_count"
          stroke="#22c55e"
          strokeWidth={2}
          dot={{ r: 3 }}
          name="closed_count"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
