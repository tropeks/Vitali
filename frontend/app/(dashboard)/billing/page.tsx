'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken, UserDTO } from '@/lib/auth';

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-600',
  pending: 'bg-yellow-100 text-yellow-700',
  submitted: 'bg-blue-100 text-blue-700',
  paid: 'bg-green-100 text-green-700',
  denied: 'bg-red-100 text-red-700',
  appeal: 'bg-orange-100 text-orange-700',
};

const STATUS_LABEL: Record<string, string> = {
  draft: 'Rascunho',
  pending: 'Pendente',
  submitted: 'Enviado',
  paid: 'Pago',
  denied: 'Glosado',
  appeal: 'Recurso',
};

function apiFetch(path: string) {
  const token = getAccessToken();
  if (!token) return Promise.reject(new Error('Sessão expirada'));
  return fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); });
}

function currentMonthLabel() {
  return new Date().toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
}

function fmtCurrency(val: any) {
  if (val == null) return '—';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function useTUSSSyncStatus() {
  const [syncStatus, setSyncStatus] = useState<any>(null);

  useEffect(() => {
    apiFetch('/ai/tuss-sync-status/')
      .then(data => setSyncStatus(data))
      .catch(() => {}); // Non-admin users get 403 — silently ignore
  }, []);

  return syncStatus;
}

function TUSSSyncStatusBadge({ syncStatus }: { syncStatus: any }) {
  if (!syncStatus) return null;
  const lastSync = syncStatus.last_syncs?.[0];
  const ageDays = syncStatus.last_sync_age_days;

  const isStale = ageDays != null && ageDays > 7;
  const badgeClass = isStale
    ? 'bg-orange-50 border-orange-300 text-orange-700'
    : 'bg-gray-50 border-gray-200 text-gray-500';

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs border rounded-full ${badgeClass}`}
      title={lastSync ? `${lastSync.row_count_total} procedimentos — ${lastSync.status}` : ''}
    >
      <span>TUSS</span>
      {ageDays != null ? (
        <span>{isStale ? `⚠ ${ageDays}d sem atualização` : `✓ Atualizado há ${ageDays}d`}</span>
      ) : (
        <span>Sem dados</span>
      )}
    </span>
  );
}

export default function BillingOverviewPage() {
  const router = useRouter();
  const [guides, setGuides] = useState<any[]>([]);
  const [batches, setBatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const syncStatus = useTUSSSyncStatus();

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }

    Promise.all([
      apiFetch('/billing/guides/?ordering=-created_at&limit=10'),
      apiFetch('/billing/batches/?status=open'),
    ])
      .then(([g, b]) => {
        setGuides(Array.isArray(g) ? g : g.results ?? []);
        setBatches(Array.isArray(b) ? b : b.results ?? []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const total = guides.length;
  const submitted = guides.filter(g => g.status === 'submitted').length;
  const awaiting = guides.filter(g => g.status === 'draft' || g.status === 'pending').length;
  const denied = guides.filter(g => g.status === 'denied').length;

  const kpis = [
    { label: 'Guias este Mês', value: total, color: 'text-blue-600' },
    { label: 'Guias Enviadas', value: submitted, color: 'text-green-600' },
    { label: 'Aguardando Envio', value: awaiting, color: 'text-yellow-600' },
    { label: 'Glosas', value: denied, color: 'text-red-600' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Faturamento</h1>
        <div className="flex items-center gap-2 mt-1">
          <p className="text-sm text-gray-500 capitalize">{currentMonthLabel()}</p>
          <TUSSSyncStatusBadge syncStatus={syncStatus} />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map(k => (
          <div key={k.label} className="bg-white rounded-xl border border-gray-200 p-5">
            <p className="text-sm text-gray-500">{k.label}</p>
            {loading
              ? <div className="h-8 w-16 mt-2 bg-gray-100 rounded animate-pulse" />
              : <p className={`text-3xl font-semibold mt-1 ${k.color}`}>{k.value}</p>
            }
          </div>
        ))}
      </div>

      {/* Recent Guides */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900">Guias Recentes</h2>
          <button
            onClick={() => router.push('/billing/guides')}
            className="text-sm text-blue-600 hover:underline"
          >
            Ver todas
          </button>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Nº da Guia', 'Paciente', 'Operadora', 'Competência', 'Valor', 'Status'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : guides.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-gray-400">
                  Nenhuma guia encontrada
                </td>
              </tr>
            ) : guides.map(g => (
              <tr
                key={g.id}
                className="hover:bg-blue-50 cursor-pointer transition-colors"
                onClick={() => router.push(`/billing/guides/${g.id}`)}
              >
                <td className="px-4 py-3 font-mono text-gray-700">{g.guide_number ?? g.id}</td>
                <td className="px-4 py-3 text-gray-900">{g.patient_name ?? g.patient ?? '—'}</td>
                <td className="px-4 py-3 text-gray-600">{g.provider_name ?? '—'}</td>
                <td className="px-4 py-3 text-gray-600">{g.competency ?? '—'}</td>
                <td className="px-4 py-3 text-gray-700">{fmtCurrency(g.total_value)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[g.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABEL[g.status] ?? g.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Open Batches */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900">Lotes Abertos</h2>
          <button
            onClick={() => router.push('/billing/batches')}
            className="text-sm text-blue-600 hover:underline"
          >
            Ver todos
          </button>
        </div>
        {loading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-10 bg-gray-100 rounded animate-pulse" />
            ))}
          </div>
        ) : batches.length === 0 ? (
          <p className="px-5 py-8 text-sm text-center text-gray-400">Nenhum lote aberto</p>
        ) : (
          <ul className="divide-y divide-gray-50">
            {batches.map(b => (
              <li
                key={b.id}
                className="flex items-center justify-between px-5 py-3 hover:bg-blue-50 cursor-pointer transition-colors"
                onClick={() => router.push(`/billing/batches/${b.id}`)}
              >
                <div>
                  <span className="font-medium text-gray-900 text-sm">Lote {b.batch_number}</span>
                  <span className="ml-2 text-xs text-gray-500">{b.provider_name ?? '—'}</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  <span>{b.guide_count ?? 0} guia(s)</span>
                  {b.closed_at && <span>Fechado {new Date(b.closed_at).toLocaleDateString('pt-BR')}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
