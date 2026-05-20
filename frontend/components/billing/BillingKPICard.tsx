'use client';

interface Props {
  label: string;
  value: string;
  sublabel?: string;
  highlight?: 'danger' | 'warning' | 'neutral';
}

export default function BillingKPICard({ label, value, sublabel, highlight }: Props) {
  const valueColor =
    highlight === 'danger'
      ? 'text-red-600'
      : highlight === 'warning'
      ? 'text-yellow-600'
      : 'text-slate-900';

  return (
    <div
      className="bg-white rounded-lg border border-slate-200 p-5"
      aria-label={`${label}: ${value}${sublabel ? ' ' + sublabel : ''}`}
    >
      <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${valueColor}`}>{value}</p>
      {sublabel && <p className="mt-0.5 text-xs text-slate-400">{sublabel}</p>}
    </div>
  );
}
