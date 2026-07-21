'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-neu-app text-neu-inkSoft',
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

function fmtCurrency(val: any) {
  if (val == null) return '—';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export default function GuidesPage() {
  const router = useRouter();
  const [guides, setGuides] = useState<any[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (search) params.set('search', search);
      const res = await fetch(`/api/v1/billing/guides/?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      const results = Array.isArray(data) ? data : data.results ?? [];
      setGuides(results);
      setCount(Array.isArray(data) ? results.length : data.count ?? results.length);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, search]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Guias TISS</h1>
          <p className="text-sm text-neu-inkMuted mt-1">{count} guia{count !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => router.push('/billing/guides/new')}
          className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover"
        >
          + Nova Guia
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* Filter bar */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
        >
          <option value="">Todos</option>
          <option value="draft">Rascunho</option>
          <option value="pending">Pendente</option>
          <option value="submitted">Enviado</option>
          <option value="paid">Pago</option>
          <option value="denied">Glosado</option>
          <option value="appeal">Recurso</option>
        </select>
        <input
          type="text"
          placeholder="Buscar por nº guia ou paciente..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none w-64"
        />
        {(statusFilter || search) && (
          <button
            onClick={() => { setStatusFilter(''); setSearch(''); }}
            className="text-sm text-neu-inkMuted hover:text-neu-inkSoft underline"
          >
            Limpar filtros
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-neu-panel border-b border-slate-100">
            <tr>
              {['Nº Guia', 'Paciente', 'Operadora', 'Competência', 'Valor', 'Status', ''].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-neu-inkMuted uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-neu-app rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : guides.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                  {search || statusFilter ? 'Nenhuma guia encontrada para os filtros.' : 'Nenhuma guia cadastrada ainda.'}
                </td>
              </tr>
            ) : guides.map(g => (
              <tr key={g.id} className="hover:bg-blue-50 transition-colors">
                <td className="px-4 py-3 font-mono text-neu-inkSoft">{g.guide_number ?? g.id}</td>
                <td className="px-4 py-3 text-neu-ink font-medium">{g.patient_name ?? g.patient ?? '—'}</td>
                <td className="px-4 py-3 text-neu-inkSoft">{g.provider_name ?? '—'}</td>
                <td className="px-4 py-3 text-neu-inkSoft">{g.competency ?? '—'}</td>
                <td className="px-4 py-3 text-neu-inkSoft">{fmtCurrency(g.total_value)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[g.status] ?? 'bg-neu-app text-neu-inkSoft'}`}>
                    {STATUS_LABEL[g.status] ?? g.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => router.push(`/billing/guides/${g.id}`)}
                    className="text-neu-brand hover:underline text-xs"
                  >
                    Ver
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
