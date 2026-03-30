'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

function fmtDate(val: any) {
  if (!val) return '—';
  return new Date(val).toLocaleDateString('pt-BR');
}

export default function PriceTablesPage() {
  const router = useRouter();
  const [tables, setTables] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoading(false); return; }
    fetch('/api/v1/billing/price-tables/', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then(data => setTables(Array.isArray(data) ? data : data.results ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const isActive = (t: any) => {
    const now = new Date();
    const from = t.valid_from ? new Date(t.valid_from) : null;
    const until = t.valid_until ? new Date(t.valid_until) : null;
    if (from && now < from) return false;
    if (until && now > until) return false;
    return true;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Tabelas de Preços</h1>
        <p className="text-sm text-gray-500 mt-1">{tables.length} tabela{tables.length !== 1 ? 's' : ''}</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['Operadora', 'Nome', 'Válida De', 'Válida Até', 'Itens', 'Status'].map(h => (
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
            ) : tables.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-16 text-center">
                  <div className="space-y-2">
                    <p className="text-gray-400 font-medium">Nenhuma tabela de preços cadastrada</p>
                    <p className="text-xs text-gray-400">As tabelas de preços são configuradas pelo administrador do sistema.</p>
                  </div>
                </td>
              </tr>
            ) : tables.map(t => {
              const active = isActive(t);
              return (
                <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-gray-900 font-medium">{t.provider_name ?? t.provider ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-800">{t.name ?? t.nome ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(t.valid_from)}</td>
                  <td className="px-4 py-3 text-gray-600">{fmtDate(t.valid_until)}</td>
                  <td className="px-4 py-3 text-gray-600">{t.item_count ?? t.items_count ?? '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                      {active ? 'Ativa' : 'Inativa'}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
