'use client';

import { useRouter } from 'next/navigation';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

interface InsurerRow {
  insurer_name: string;
  ans_code: string;
  total_guides: number;
  denied_guides: number;
  denial_rate: number;
  denied_value: string;
}

interface Props {
  data: InsurerRow[];
}

function fmt(val: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }).format(val);
}

export default function DenialByInsurerChart({ data }: Props) {
  const router = useRouter();
  const top5 = data.slice(0, 5);

  const chartData = top5.map(r => ({
    name: r.insurer_name.length > 16 ? r.insurer_name.slice(0, 16) + '…' : r.insurer_name,
    denied_value: Number(r.denied_value),
    denial_rate: Math.round(r.denial_rate * 100),
    ans_code: r.ans_code,
    full_name: r.insurer_name,
  }));

  function handleClick(ans_code: string) {
    router.push(`/billing/guides?status=denied&provider=${ans_code}`);
  }

  function handleKeyDown(e: React.KeyboardEvent, ans_code: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleClick(ans_code);
    }
  }

  if (chartData.length === 0) {
    return (
      <p className="text-sm text-gray-400 text-center py-6">Sem dados para o período</p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(180, chartData.length * 56)}>
      <BarChart
        data={chartData}
        layout="vertical"
        margin={{ top: 4, right: 64, left: 0, bottom: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={v => `R$${(v / 1000).toFixed(0)}k`}
          tick={{ fontSize: 11, fill: '#6b7280' }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fontSize: 12, fill: '#374151' }}
          tickLine={false}
          axisLine={false}
          width={120}
        />
        <Tooltip
          formatter={(val: number, _name, props) => [
            fmt(val),
            `${props.payload.full_name} — ${props.payload.denial_rate}% glosado`,
          ]}
        />
        <Bar dataKey="denied_value" barSize={44} radius={[0, 4, 4, 0]}>
          {chartData.map(entry => (
            <Cell
              key={entry.ans_code}
              fill="#ef4444"
              className="cursor-pointer hover:opacity-80 transition-opacity"
              tabIndex={0}
              onClick={() => handleClick(entry.ans_code)}
              onKeyDown={(e: React.KeyboardEvent) => handleKeyDown(e, entry.ans_code)}
              aria-label={`${entry.full_name}: ${fmt(Number(entry.denied_value))} glosado. Clique para ver guias.`}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
