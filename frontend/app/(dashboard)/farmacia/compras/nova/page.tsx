'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';
import { Plus, Trash2 } from 'lucide-react';

interface Supplier {
  id: string;
  name: string;
}

interface Drug {
  id: string;
  name: string;
  dosage_form: string;
  concentration: string;
}

interface POItem {
  drug_id: string;
  drug_name: string;
  quantity: string;
  unit_price: string;
}

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>;
  return ((...args: any[]) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  }) as T;
}

function extractError(err: unknown): string {
  if (typeof err === 'string') return err;
  const obj = err as Record<string, unknown>;
  if (obj?.detail) return String(obj.detail);
  const firstVal = Object.values(obj ?? {})[0];
  if (Array.isArray(firstVal)) return String(firstVal[0]);
  if (typeof firstVal === 'string') return firstVal;
  return 'Erro ao salvar. Tente novamente.';
}

export default function NovaCompraPage() {
  const router = useRouter();

  // Supplier
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierQuery, setSupplierQuery] = useState('');
  const [selectedSupplier, setSelectedSupplier] = useState<Supplier | null>(null);
  const [supplierOpen, setSupplierOpen] = useState(false);

  // Form
  const [expectedDate, setExpectedDate] = useState('');
  const [notes, setNotes] = useState('');

  // Items
  const [items, setItems] = useState<POItem[]>([]);
  const [drugQuery, setDrugQuery] = useState('');
  const [drugResults, setDrugResults] = useState<Drug[]>([]);
  const [loadingDrugs, setLoadingDrugs] = useState(false);
  const [addingDrug, setAddingDrug] = useState<Drug | null>(null);
  const [addQty, setAddQty] = useState('');
  const [addPrice, setAddPrice] = useState('');

  // Submit
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    async function loadSuppliers() {
      const token = getAccessToken();
      if (!token) return;
      const res = await fetch('/api/v1/pharmacy/suppliers/', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setSuppliers(data.results ?? data ?? []);
      }
    }
    loadSuppliers();
  }, []);

  const searchDrugs = useCallback(
    debounce(async (q: string) => {
      if (!q.trim()) {
        setDrugResults([]);
        return;
      }
      setLoadingDrugs(true);
      try {
        const token = getAccessToken();
        const res = await fetch(
          `/api/v1/pharmacy/drugs/?search=${encodeURIComponent(q)}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (res.ok) {
          const data = await res.json();
          setDrugResults(data.results ?? data ?? []);
        }
      } finally {
        setLoadingDrugs(false);
      }
    }, 300),
    []
  );

  const filteredSuppliers = suppliers.filter((s) =>
    s.name.toLowerCase().includes(supplierQuery.toLowerCase())
  );

  function selectDrugForAdd(drug: Drug) {
    setAddingDrug(drug);
    setDrugQuery('');
    setDrugResults([]);
    setAddQty('');
    setAddPrice('');
  }

  function confirmAddItem() {
    if (!addingDrug || !addQty) return;
    setItems((prev) => [
      ...prev,
      {
        drug_id: addingDrug.id,
        drug_name: addingDrug.name,
        quantity: addQty,
        unit_price: addPrice || '0',
      },
    ]);
    setAddingDrug(null);
    setAddQty('');
    setAddPrice('');
  }

  function removeItem(index: number) {
    setItems((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedSupplier) {
      setError('Selecione um fornecedor.');
      return;
    }
    if (items.length === 0) {
      setError('Adicione pelo menos um item.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const token = getAccessToken();
      if (!token) {
        setError('Sessão expirada. Faça login novamente.');
        return;
      }
      const body = {
        supplier: selectedSupplier.id,
        expected_date: expectedDate || null,
        notes,
        items: items.map((it) => ({
          drug: it.drug_id,
          quantity_ordered: parseFloat(it.quantity),
          unit_price: parseFloat(it.unit_price) || 0,
        })),
      };
      const res = await fetch('/api/v1/pharmacy/purchase-orders/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json();
        setError(extractError(data));
        return;
      }
      const created = await res.json();
      router.push(`/farmacia/compras/${created.id}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <button
          onClick={() => router.back()}
          className="text-xs text-blue-600 hover:underline mb-2 inline-block"
        >
          ← Voltar
        </button>
        <h2 className="text-lg font-semibold text-slate-900">Nova Ordem de Compra</h2>
      </div>

      {error && (
        <div
          role="alert"
          className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm"
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Supplier search */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <h3 className="text-sm font-semibold text-slate-800">Dados Gerais</h3>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-600">
              Fornecedor *
            </label>
            {selectedSupplier ? (
              <div className="flex items-center justify-between px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
                <span className="text-sm font-medium text-blue-900">
                  {selectedSupplier.name}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedSupplier(null);
                    setSupplierQuery('');
                  }}
                  className="text-xs text-blue-600 hover:underline"
                >
                  Alterar
                </button>
              </div>
            ) : (
              <div className="relative">
                <input
                  type="text"
                  placeholder="Buscar fornecedor..."
                  value={supplierQuery}
                  onChange={(e) => {
                    setSupplierQuery(e.target.value);
                    setSupplierOpen(true);
                  }}
                  onFocus={() => setSupplierOpen(true)}
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {supplierOpen && filteredSuppliers.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                    {filteredSuppliers.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => {
                          setSelectedSupplier(s);
                          setSupplierQuery(s.name);
                          setSupplierOpen(false);
                        }}
                        className="w-full text-left px-3 py-2 hover:bg-slate-50 text-sm"
                      >
                        {s.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Data prevista de entrega
              </label>
              <input
                type="date"
                value={expectedDate}
                onChange={(e) => setExpectedDate(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Observações
            </label>
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Condições de entrega, contato, etc."
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Items */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <h3 className="text-sm font-semibold text-slate-800">Itens</h3>

          {/* Items table */}
          {items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[420px]">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left py-2 pr-3 text-xs font-medium text-slate-500">
                      Medicamento
                    </th>
                    <th className="text-left py-2 pr-3 text-xs font-medium text-slate-500">
                      Qtd.
                    </th>
                    <th className="text-left py-2 pr-3 text-xs font-medium text-slate-500">
                      Preço unit.
                    </th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item, i) => (
                    <tr key={i} className="border-b border-slate-50">
                      <td className="py-2 pr-3 font-medium text-slate-800">
                        {item.drug_name}
                      </td>
                      <td className="py-2 pr-3 font-mono text-slate-700">
                        {item.quantity}
                      </td>
                      <td className="py-2 pr-3 font-mono text-slate-700">
                        {parseFloat(item.unit_price) > 0
                          ? `R$ ${parseFloat(item.unit_price).toFixed(2)}`
                          : '—'}
                      </td>
                      <td className="py-2">
                        <button
                          type="button"
                          onClick={() => removeItem(i)}
                          className="text-slate-400 hover:text-red-500"
                          title="Remover"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Add item flow */}
          {addingDrug ? (
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-3">
              <p className="text-sm font-medium text-slate-800">{addingDrug.name}</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Quantidade *
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    min="0.001"
                    value={addQty}
                    onChange={(e) => setAddQty(e.target.value)}
                    placeholder="Ex: 100"
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Preço unitário (R$)
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={addPrice}
                    onChange={(e) => setAddPrice(e.target.value)}
                    placeholder="Ex: 12.50"
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={confirmAddItem}
                  disabled={!addQty}
                  className="px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  Adicionar item
                </button>
                <button
                  type="button"
                  onClick={() => setAddingDrug(null)}
                  className="px-3 py-2 text-xs text-slate-600 hover:text-slate-900"
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <label className="block text-xs font-medium text-slate-600">
                Buscar medicamento para adicionar
              </label>
              <input
                type="text"
                placeholder="Digite o nome do medicamento..."
                value={drugQuery}
                onChange={(e) => {
                  setDrugQuery(e.target.value);
                  searchDrugs(e.target.value);
                }}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              {loadingDrugs && (
                <p className="text-xs text-slate-400">Buscando...</p>
              )}
              {drugResults.length > 0 && (
                <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 overflow-hidden">
                  {drugResults.slice(0, 8).map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => selectDrugForAdd(d)}
                      className="w-full text-left px-3 py-2 hover:bg-slate-50 text-sm"
                    >
                      <span className="font-medium text-slate-900">{d.name}</span>
                      {(d.dosage_form || d.concentration) && (
                        <span className="text-slate-400 ml-2 text-xs">
                          {[d.dosage_form, d.concentration].filter(Boolean).join(' ')}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={saving}
            className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? 'Salvando...' : 'Criar Ordem de Compra'}
          </button>
          <button
            type="button"
            onClick={() => router.back()}
            className="px-4 py-2.5 text-sm text-slate-600 hover:text-slate-900"
          >
            Cancelar
          </button>
        </div>
      </form>
    </div>
  );
}
