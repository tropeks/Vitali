'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';
import { Loader2, AlertCircle, CheckCircle } from 'lucide-react';

interface POItem {
  id: string;
  drug_name: string;
  quantity_ordered: number;
  unit_price: number | null;
  quantity_received: number | null;
}

interface PurchaseOrder {
  id: string;
  supplier_name: string;
  expected_date: string | null;
  status: string;
  notes: string;
  updated_at: string;
  items: POItem[];
}

interface ReceiptEntry {
  item_id: string;
  quantity_received: string;
  lot_number: string;
  expiry_date: string;
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

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
  return d.toLocaleDateString('pt-BR');
}

function formatCurrency(val: number | null): string {
  if (val === null || val === undefined) return '—';
  return val.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

export default function PODetailPage() {
  const router = useRouter();
  const params = useParams();
  const id = params?.id as string;

  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [loading, setLoading] = useState(true);

  // Receipt state
  const [registering, setRegistering] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Per-item receipt entries
  const [entries, setEntries] = useState<Record<string, ReceiptEntry>>({});

  async function load() {
    const token = getAccessToken();
    if (!token) return;
    try {
      const res = await fetch(`/api/v1/pharmacy/purchase-orders/${id}/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const data: PurchaseOrder = await res.json();
      setOrder(data);
      // Pre-populate entry fields
      const initial: Record<string, ReceiptEntry> = {};
      for (const item of data.items) {
        initial[item.id] = {
          item_id: item.id,
          quantity_received: '',  // always start empty — existing received shown as read-only context
          lot_number: '',
          expiry_date: '',
        };
      }
      setEntries(initial);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function updateEntry(itemId: string, field: keyof ReceiptEntry, value: string) {
    setEntries((prev) => ({
      ...prev,
      [itemId]: { ...prev[itemId], [field]: value },
    }));
  }

  async function handleRegisterReceipt() {
    const token = getAccessToken();
    if (!token || !order) return;

    setRegistering(true);
    setReceiptError(null);
    setDemoMode(false);

    try {
      const payload = Object.values(entries).map((e) => ({
        item_id: e.item_id,
        quantity_received: parseFloat(e.quantity_received) || 0,
        lot_number: e.lot_number,
        expiry_date: e.expiry_date || null,
      }));

      const res = await fetch(`/api/v1/pharmacy/purchase-orders/${id}/receive/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ items: payload }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg: string =
          typeof data === 'string'
            ? data
            : data?.detail ?? data?.error ?? JSON.stringify(data) ?? 'Erro desconhecido.';

        if (msg.includes('[DEMO]')) {
          setDemoMode(true);
        } else {
          setReceiptError(msg);
        }
        return;
      }

      // Success
      setToast('Recebimento registrado. Estoque atualizado.');
      toastTimer.current = setTimeout(() => {
        setToast(null);
        load(); // reload the page data
      }, 4000);
    } finally {
      setRegistering(false);
    }
  }

  const canReceive =
    order && order.status !== 'received' && order.status !== 'cancelled';

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-7 bg-slate-200 rounded w-64" />
        <div className="h-48 bg-slate-200 rounded-xl" />
      </div>
    );
  }

  if (!order) {
    return (
      <div className="text-center py-16 space-y-3">
        <AlertCircle size={40} className="text-slate-300 mx-auto" />
        <p className="text-slate-500">Ordem de compra não encontrada.</p>
        <button
          onClick={() => router.push('/farmacia/compras')}
          className="text-sm text-blue-600 hover:underline"
        >
          Voltar para ordens
        </button>
      </div>
    );
  }

  const statusMeta = STATUS_BADGE[order.status] ?? 'bg-slate-100 text-slate-600';
  const statusLabel = STATUS_LABELS[order.status] ?? order.status;

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Toast */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed top-4 right-4 z-50 flex items-center gap-2 bg-green-700 text-white text-sm font-medium px-4 py-3 rounded-xl shadow-lg"
        >
          <CheckCircle size={16} />
          {toast}
        </div>
      )}

      {/* Header */}
      <div>
        <button
          onClick={() => router.push('/farmacia/compras')}
          className="text-xs text-blue-600 hover:underline mb-2 inline-block"
        >
          ← Ordens de Compra
        </button>
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-xl font-bold text-slate-900">{order.supplier_name}</h2>
            <p className="text-sm text-slate-500 mt-0.5">
              Previsto: {formatDate(order.expected_date)} · Atualizado:{' '}
              {formatDate(order.updated_at)}
            </p>
          </div>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${statusMeta}`}>
            {statusLabel}
          </span>
        </div>
        {order.notes && (
          <p className="mt-2 text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-4 py-2">
            {order.notes}
          </p>
        )}
      </div>

      {/* Demo mode banner */}
      {demoMode && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center gap-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-4 py-3 text-sm"
        >
          <AlertCircle size={18} className="shrink-0" />
          <p>
            <span className="font-semibold">Modo demo:</span> O recebimento foi simulado mas não
            foi efetivado. Configure um ambiente real para registrar entradas de estoque.
          </p>
        </div>
      )}

      {/* Items table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between gap-4 flex-wrap">
          <h3 className="font-semibold text-slate-900">Itens da Ordem</h3>
          <span className="text-xs text-slate-400">
            {order.items.length} {order.items.length === 1 ? 'item' : 'itens'}
          </span>
        </div>

        {/* Receipt error banner — inside items section */}
        {receiptError && (
          <div
            role="alert"
            aria-live="polite"
            className="mx-5 mt-4 flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm"
          >
            <AlertCircle size={16} className="shrink-0 mt-0.5" />
            <p>{receiptError}</p>
          </div>
        )}

        {/* Desktop table */}
        <div className="hidden sm:block overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-5 py-3 text-xs font-medium text-slate-500">
                  Medicamento
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">
                  Qtd. Pedida
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">
                  Preço unit.
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">
                  Qtd. Recebida
                </th>
                {canReceive && (
                  <>
                    <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">
                      Lote
                    </th>
                    <th className="text-left px-4 py-3 text-xs font-medium text-slate-500">
                      Validade
                    </th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {order.items.map((item) => (
                <tr key={item.id} className="border-b border-slate-50 hover:bg-slate-50">
                  <td className="px-5 py-3 font-medium text-slate-900">{item.drug_name}</td>
                  <td className="px-4 py-3 font-mono text-slate-700">{item.quantity_ordered}</td>
                  <td className="px-4 py-3 text-slate-600">{formatCurrency(item.unit_price)}</td>
                  <td className="px-4 py-3">
                    {canReceive ? (
                      <input
                        type="number"
                        step="0.001"
                        min="0"
                        value={entries[item.id]?.quantity_received ?? ''}
                        onChange={(e) =>
                          updateEntry(item.id, 'quantity_received', e.target.value)
                        }
                        className="w-24 border border-slate-200 rounded px-2 py-1 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="0"
                      />
                    ) : (
                      <span className="font-mono text-slate-700">
                        {item.quantity_received ?? '—'}
                      </span>
                    )}
                  </td>
                  {canReceive && (
                    <>
                      <td className="px-4 py-3">
                        <input
                          type="text"
                          value={entries[item.id]?.lot_number ?? ''}
                          onChange={(e) => updateEntry(item.id, 'lot_number', e.target.value)}
                          className="w-32 border border-slate-200 rounded px-2 py-1 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="LOT-001"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="date"
                          value={entries[item.id]?.expiry_date ?? ''}
                          onChange={(e) => updateEntry(item.id, 'expiry_date', e.target.value)}
                          className="border border-slate-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile card layout */}
        <div className="sm:hidden divide-y divide-slate-100">
          {order.items.map((item) => (
            <div key={item.id} className="p-4 space-y-3">
              <p className="font-medium text-slate-900">{item.drug_name}</p>
              <div className="flex gap-4 text-xs text-slate-500">
                <span>Pedido: {item.quantity_ordered}</span>
                <span>Preço: {formatCurrency(item.unit_price)}</span>
              </div>
              {canReceive ? (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Qtd. recebida</label>
                    <input
                      type="number"
                      step="0.001"
                      min="0"
                      value={entries[item.id]?.quantity_received ?? ''}
                      onChange={(e) =>
                        updateEntry(item.id, 'quantity_received', e.target.value)
                      }
                      className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm"
                      placeholder="0"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">Lote</label>
                    <input
                      type="text"
                      value={entries[item.id]?.lot_number ?? ''}
                      onChange={(e) => updateEntry(item.id, 'lot_number', e.target.value)}
                      className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm"
                      placeholder="LOT-001"
                    />
                  </div>
                  <div className="col-span-2">
                    <label className="block text-xs text-slate-500 mb-1">Validade</label>
                    <input
                      type="date"
                      value={entries[item.id]?.expiry_date ?? ''}
                      onChange={(e) => updateEntry(item.id, 'expiry_date', e.target.value)}
                      className="w-full border border-slate-200 rounded px-2 py-1.5 text-sm"
                    />
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500">
                  Recebido: {item.quantity_received ?? '—'}
                </p>
              )}
            </div>
          ))}
        </div>

        {/* Register receipt button */}
        {canReceive && (
          <div className="px-5 py-4 border-t border-slate-100 flex justify-end sm:justify-end">
            <button
              onClick={handleRegisterReceipt}
              disabled={registering}
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-3 sm:py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {registering && <Loader2 size={16} className="animate-spin" />}
              {registering ? 'Registrando...' : 'Registrar Recebimento'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
