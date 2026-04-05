'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';
import { Plus } from 'lucide-react';

interface PurchaseOrder {
  id: string;
  supplier_name: string;
  expected_date: string | null;
  item_count: number;
  status: 'draft' | 'sent' | 'partial' | 'received' | 'cancelled' | string;
  updated_at: string;
}

interface Supplier {
  id: string;
  name: string;
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'Rascunho',
  sent: 'Enviado',
  partial: 'Parcial',
  received: 'Recebido',
  cancelled: 'Cancelado',
};

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-600',
  sent: 'bg-blue-100 text-blue-700',
  partial: 'bg-yellow-100 text-yellow-700',
  received: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-700',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
        STATUS_BADGE[status] ?? 'bg-slate-100 text-slate-600'
      }`}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
  return d.toLocaleDateString('pt-BR');
}

const STATUS_OPTIONS = [
  { value: 'draft', label: 'Rascunho' },
  { value: 'sent', label: 'Enviado' },
  { value: 'partial', label: 'Parcial' },
  { value: 'received', label: 'Recebido' },
  { value: 'cancelled', label: 'Cancelado' },
];

export default function ComprasPage() {
  const router = useRouter();
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [supplierFilter, setSupplierFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<string[]>([]);

  useEffect(() => {
    async function load() {
      const token = getAccessToken();
      if (!token) return;
      const headers = { Authorization: `Bearer ${token}` };
      try {
        const [ordRes, supRes] = await Promise.all([
          fetch('/api/v1/pharmacy/purchase-orders/', { headers }),
          fetch('/api/v1/pharmacy/suppliers/', { headers }),
        ]);
        if (ordRes.ok) {
          const data = await ordRes.json();
          setOrders(data.results ?? data ?? []);
        }
        if (supRes.ok) {
          const data = await supRes.json();
          setSuppliers(data.results ?? data ?? []);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function toggleStatus(val: string) {
    setStatusFilter((prev) =>
      prev.includes(val) ? prev.filter((s) => s !== val) : [...prev, val]
    );
  }

  const filtered = orders.filter((o) => {
    if (supplierFilter && o.supplier_name !== supplierFilter) return false;
    if (statusFilter.length > 0 && !statusFilter.includes(o.status)) return false;
    return true;
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-lg font-semibold text-slate-900">Ordens de Compra</h2>
        <button
          onClick={() => router.push('/farmacia/compras/nova')}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={16} />
          Nova Ordem
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 items-start bg-white border border-slate-200 rounded-xl p-4">
        {/* Supplier dropdown */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">Fornecedor</label>
          <select
            value={supplierFilter}
            onChange={(e) => setSupplierFilter(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[180px]"
          >
            <option value="">Todos</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        {/* Status multi-select */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500">Status</label>
          <div className="flex flex-wrap gap-2">
            {STATUS_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex items-center gap-1.5 text-sm text-slate-600 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={statusFilter.includes(opt.value)}
                  onChange={() => toggleStatus(opt.value)}
                  className="rounded border-gray-300"
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>
      </div>

      {loading && (
        <p className="text-sm text-slate-400">Carregando...</p>
      )}

      {/* Desktop table */}
      {!loading && (
        <>
          <div className="hidden sm:block bg-white rounded-xl border border-slate-200 overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  {['Fornecedor', 'Data Prevista', 'Itens', 'Status', 'Atualizado'].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wide"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-slate-400 text-sm">
                      Nenhuma ordem de compra encontrada.
                    </td>
                  </tr>
                )}
                {filtered.map((o) => (
                  <tr
                    key={o.id}
                    className="border-b border-slate-50 hover:bg-slate-50 cursor-pointer"
                    onClick={() => router.push(`/farmacia/compras/${o.id}`)}
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{o.supplier_name}</td>
                    <td className="px-4 py-3 text-slate-600">{formatDate(o.expected_date)}</td>
                    <td className="px-4 py-3 text-slate-600">{o.item_count}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={o.status} />
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{formatDate(o.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card layout */}
          <div className="sm:hidden space-y-3">
            {filtered.length === 0 && (
              <p className="text-sm text-slate-400 text-center py-8">
                Nenhuma ordem de compra encontrada.
              </p>
            )}
            {filtered.map((o) => (
              <button
                key={o.id}
                onClick={() => router.push(`/farmacia/compras/${o.id}`)}
                className="w-full text-left bg-white rounded-xl border border-slate-200 p-4 space-y-2 hover:bg-slate-50 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-slate-900 truncate">{o.supplier_name}</p>
                  <StatusBadge status={o.status} />
                </div>
                <div className="flex gap-4 text-xs text-slate-500">
                  <span>Previsto: {formatDate(o.expected_date)}</span>
                  <span>{o.item_count} {o.item_count === 1 ? 'item' : 'itens'}</span>
                </div>
                <p className="text-xs text-slate-400">
                  Atualizado em {formatDate(o.updated_at)}
                </p>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
