'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

const STATUS_BADGE: Record<string, string> = {
  open: 'bg-blue-100 text-blue-700',
  closed: 'bg-yellow-100 text-yellow-700',
  submitted: 'bg-purple-100 text-purple-700',
  paid: 'bg-green-100 text-green-700',
  partial: 'bg-orange-100 text-orange-700',
};

const STATUS_LABEL: Record<string, string> = {
  open: 'Aberto',
  closed: 'Fechado',
  submitted: 'Enviado',
  paid: 'Pago',
  partial: 'Parcial',
};

function fmtCurrency(val: any) {
  if (val == null) return '—';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export default function BatchesPage() {
  const router = useRouter();
  const [batches, setBatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [providers, setProviders] = useState<any[]>([]);
  const [newProviderId, setNewProviderId] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const load = useCallback(async () => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      const res = await fetch(`/api/v1/billing/batches/?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setBatches(Array.isArray(data) ? data : data.results ?? []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const openCreateModal = async () => {
    setShowModal(true);
    setCreateError('');
    if (providers.length === 0) {
      const token = getAccessToken();
      if (!token) return;
      try {
        const res = await fetch('/api/v1/billing/providers/', {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        setProviders(Array.isArray(data) ? data : data.results ?? []);
      } catch { /* ignore */ }
    }
  };

  const createBatch = async () => {
    if (!newProviderId) { setCreateError('Selecione uma operadora.'); return; }
    const token = getAccessToken();
    if (!token) { setCreateError('Sessão expirada'); return; }
    setCreating(true);
    setCreateError('');
    try {
      const res = await fetch('/api/v1/billing/batches/', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: newProviderId }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `${res.status}`);
      }
      const batch = await res.json();
      setShowModal(false);
      setNewProviderId('');
      router.push(`/billing/batches/${batch.id}`);
    } catch (e: any) {
      setCreateError(e.message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Lotes TISS</h1>
          <p className="text-sm text-gray-500 mt-1">{batches.length} lote{batches.length !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={openCreateModal}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
        >
          + Novo Lote
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {/* Filter */}
      <div className="flex gap-3">
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
        >
          <option value="">Todos os status</option>
          <option value="open">Aberto</option>
          <option value="closed">Fechado</option>
          <option value="submitted">Enviado</option>
          <option value="paid">Pago</option>
        </select>
        {statusFilter && (
          <button
            onClick={() => setStatusFilter('')}
            className="text-sm text-gray-500 hover:text-gray-700 underline"
          >
            Limpar
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Nº Lote', 'Operadora', 'Guias', 'Valor Total', 'Status', 'Data Fechamento', ''].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : batches.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                  Nenhum lote encontrado
                </td>
              </tr>
            ) : batches.map(b => (
              <tr key={b.id} className="hover:bg-blue-50 transition-colors">
                <td className="px-4 py-3 font-mono text-gray-700">{b.batch_number ?? b.id}</td>
                <td className="px-4 py-3 text-gray-900">{b.provider_name ?? b.provider ?? '—'}</td>
                <td className="px-4 py-3 text-gray-600">{b.guide_count ?? 0}</td>
                <td className="px-4 py-3 text-gray-700">{fmtCurrency(b.total_value)}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[b.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABEL[b.status] ?? b.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600">
                  {b.closed_at ? new Date(b.closed_at).toLocaleDateString('pt-BR') : '—'}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => router.push(`/billing/batches/${b.id}`)}
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

      {/* Create batch modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Novo Lote TISS</h2>
            {createError && (
              <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">{createError}</div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Operadora *</label>
              <select
                value={newProviderId}
                onChange={e => setNewProviderId(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              >
                <option value="">Selecione a operadora...</option>
                {providers.map(p => (
                  <option key={p.id} value={p.id}>{p.name ?? p.provider_name ?? p.id}</option>
                ))}
              </select>
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <button
                onClick={() => { setShowModal(false); setNewProviderId(''); }}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
              >
                Cancelar
              </button>
              <button
                onClick={createBatch}
                disabled={!newProviderId || creating}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {creating ? 'Criando...' : 'Criar Lote'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
