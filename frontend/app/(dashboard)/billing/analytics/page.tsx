'use client';

import { useState, useEffect, useCallback } from 'react';
import { getAccessToken } from '@/lib/auth';
import BillingKPICard from '@/components/billing/BillingKPICard';
import RevenueChart from '@/components/billing/RevenueChart';
import DenialByInsurerChart from '@/components/billing/DenialByInsurerChart';
import BatchThroughputChart from '@/components/billing/BatchThroughputChart';
import GlosaAccuracyTable from '@/components/billing/GlosaAccuracyTable';

// ─── Data fetching ───────────────────────────────────────────────────────────

function apiFetch(path: string) {
  const token = getAccessToken();
  if (!token) return Promise.reject(new Error('Sessão expirada'));
  return fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(r => {
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  });
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtCurrency(val: string | number | null | undefined) {
  if (val == null) return 'R$ 0,00';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function fmtPct(val: number | null | undefined) {
  if (val == null) return '0,0%';
  return (val * 100).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SectionError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 flex items-center justify-between">
      <p className="text-sm text-red-700">Não foi possível carregar os dados. Tente novamente.</p>
      <button
        type="button"
        onClick={onRetry}
        className="ml-4 text-sm text-red-700 border border-red-300 rounded px-3 py-1 hover:bg-red-100 transition-colors"
      >
        Tentar novamente
      </button>
    </div>
  );
}

function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div
      className="animate-pulse bg-gray-100 rounded-lg"
      style={{ height }}
      aria-hidden="true"
    />
  );
}

function PeriodToggle({
  value,
  onChange,
}: {
  value: number;
  onChange: (m: number) => void;
}) {
  const options = [
    { label: '3m', months: 3 },
    { label: '6m', months: 6 },
    { label: '12m', months: 12 },
  ];
  return (
    <div role="group" aria-label="Período" className="flex flex-wrap gap-1">
      {options.map(o => (
        <button
          key={o.months}
          type="button"
          onClick={() => onChange(o.months)}
          className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
            value === o.months
              ? 'bg-blue-600 text-white'
              : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

type LoadState<T> = { status: 'idle' | 'loading' | 'ok' | 'error'; data: T | null };

function useEndpoint<T>(url: string | null): [LoadState<T>, () => void] {
  const [state, setState] = useState<LoadState<T>>({ status: 'idle', data: null });

  const load = useCallback(() => {
    if (!url) return;
    setState(s => ({ ...s, status: 'loading' }));
    apiFetch(url)
      .then(data => setState({ status: 'ok', data }))
      .catch(() => setState({ status: 'error', data: null }));
  }, [url]);

  useEffect(() => {
    load();
  }, [load]);

  return [state, load];
}

export default function BillingAnalyticsPage() {
  const [months, setMonths] = useState(6);

  // KPI — always current month (no months param)
  const [overview, retryOverview] = useEndpoint<any>(
    '/analytics/billing/overview/'
  );

  // Charts — respond to period toggle
  const [revenue, retryRevenue] = useEndpoint<any[]>(
    `/analytics/billing/monthly-revenue/?months=${months}`
  );
  const [denial, retryDenial] = useEndpoint<any[]>(
    `/analytics/billing/denial-by-insurer/?months=${months}`
  );
  const [throughput, retryThroughput] = useEndpoint<any[]>(
    `/analytics/billing/batch-throughput/?months=${months}`
  );
  const [accuracy, retryAccuracy] = useEndpoint<any[]>(
    '/analytics/billing/glosa-accuracy/'
  );

  const isLoading = (s: LoadState<any>) => s.status === 'loading' || s.status === 'idle';

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Inteligência de Faturamento</h1>
          <p className="text-sm text-gray-500 mt-0.5">Análise de receita, glosas e lotes TISS</p>
        </div>
        <PeriodToggle value={months} onChange={setMonths} />
      </div>

      {/* KPI Cards — always current month */}
      {isLoading(overview) ? (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="animate-pulse bg-gray-100 rounded-xl h-24" />
          ))}
        </div>
      ) : overview.status === 'error' ? (
        <SectionError onRetry={retryOverview} />
      ) : overview.data ? (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
          <BillingKPICard
            label="Taxa de Glosa"
            value={fmtPct(overview.data.denial_rate)}
            sublabel="Mês atual"
            highlight={overview.data.denial_rate > 0.15 ? 'danger' : overview.data.denial_rate > 0.08 ? 'warning' : 'neutral'}
          />
          <BillingKPICard
            label="Total Glosado"
            value={fmtCurrency(overview.data.total_denied)}
            sublabel="Mês atual"
            highlight={Number(overview.data.total_denied) > 0 ? 'danger' : 'neutral'}
          />
          <BillingKPICard
            label="Total Faturado"
            value={fmtCurrency(overview.data.total_billed)}
            sublabel="Mês atual"
          />
          <BillingKPICard
            label="Total Pago"
            value={fmtCurrency(overview.data.total_collected)}
            sublabel="Mês atual"
          />
        </div>
      ) : null}

      {/* Denial by Insurer — 2nd (actionable) */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Glosa por Convênio</h2>
        <p className="text-xs text-gray-400 mb-3">Top 5 por valor glosado · mínimo 10 guias</p>
        {isLoading(denial) ? (
          <ChartSkeleton height={220} />
        ) : denial.status === 'error' ? (
          <SectionError onRetry={retryDenial} />
        ) : denial.data && denial.data.length > 0 ? (
          <DenialByInsurerChart data={denial.data} />
        ) : (
          <p className="text-sm text-gray-400 text-center py-6">Sem dados para o período</p>
        )}
      </div>

      {/* Revenue Trend — 3rd (contextual) */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Tendência de Receita</h2>
        {isLoading(revenue) ? (
          <ChartSkeleton />
        ) : revenue.status === 'error' ? (
          <SectionError onRetry={retryRevenue} />
        ) : revenue.data ? (
          <RevenueChart data={revenue.data} />
        ) : null}
      </div>

      {/* Batch Throughput */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Throughput de Lotes</h2>
        {isLoading(throughput) ? (
          <ChartSkeleton height={220} />
        ) : throughput.status === 'error' ? (
          <SectionError onRetry={retryThroughput} />
        ) : throughput.data ? (
          <BatchThroughputChart data={throughput.data} />
        ) : null}
      </div>

      {/* Glosa AI Accuracy — 5th */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Precisão da IA de Glosa</h2>
        <p className="text-xs text-gray-400 mb-4">Previsões com resultado confirmado pelo retorno</p>
        {isLoading(accuracy) ? (
          <ChartSkeleton height={120} />
        ) : accuracy.status === 'error' ? (
          <SectionError onRetry={retryAccuracy} />
        ) : (
          <GlosaAccuracyTable data={accuracy.data ?? []} />
        )}
      </div>
    </div>
  );
}
