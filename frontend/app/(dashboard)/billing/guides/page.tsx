'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

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
          <h1 className="text-2xl font-semibold text-gray-900">Guias TISS</h1>
          <p className="text-sm text-gray-500 mt-1">{count} guia{count !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => router.push('/billing/guides/new')}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
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
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
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
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none w-64"
        />
        {(statusFilter || search) && (
          <button
            onClick={() => { setStatusFilter(''); setSearch(''); }}
            className="text-sm text-gray-500 hover:text-gray-700 underline"
          >
            Limpar filtros
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Nº Guia', 'Paciente', 'Operadora', 'Competência', 'Valor', 'Status', ''].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : guides.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                  {search || statusFilter ? 'Nenhuma guia encontrada para os filtros.' : 'Nenhuma guia cadastrada ainda.'}
                </td>
              </tr>
            ) : guides.map(g => (
              <tr key={g.id} className="hover:bg-blue-50 transition-colors">
                <td className="px-4 py-3 font-mono text-gray-700">{g.guide_number ?? g.id}</td>
                <td className="px-4 py-3 text-gray-900 font-medium">{g.patient_name ?? g.patient ?? '—'}</td>
                <td className="px-4 py-3 text-gray-600">{g.provider_name ?? '—'}</td>
                <td className="px-4 py-3 text-gray-600">{g.competency ?? '—'}</td>
                <td className="px-4 py-3 text-gray-700">{fmtCurrency(g.total_value)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[g.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABEL[g.status] ?? g.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => router.push(`/billing/guides/${g.id}`)}
                    className="text-blue-600 hover:underline text-xs"
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
