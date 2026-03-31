'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';
import TUSSCodeSearch, { TUSSOption } from '@/components/billing/TUSSCodeSearch';
import TUSSSuggestionInline, { TUSSSuggestion } from '@/components/billing/TUSSSuggestionInline';

function apiFetch(path: string) {
  const token = getAccessToken();
  if (!token) return Promise.reject(new Error('Sessão expirada'));
  return fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); });
}

interface GuideItem {
  tuss_code: TUSSOption | null;
  description: string;
  quantity: number;
  unit_value: string;
}

const emptyItem = (): GuideItem => ({ tuss_code: null, description: '', quantity: 1, unit_value: '' });

export default function NewGuidePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const prefillEncounter = searchParams.get('encounter') ?? '';

  const [patients, setPatients] = useState<any[]>([]);
  const [providers, setProviders] = useState<any[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [form, setForm] = useState({
    encounter_id: prefillEncounter,
    patient_id: '',
    provider_id: '',
    insured_card_number: '',
    competency: new Date().toISOString().slice(0, 7), // default YYYY-MM
    guide_type: 'sadt',
  });

  const [items, setItems] = useState<GuideItem[]>([emptyItem()]);

  useEffect(() => {
    Promise.all([
      apiFetch('/emr/patients/?page_size=200'),
      apiFetch('/billing/providers/'),
    ])
      .then(([p, prov]) => {
        setPatients(Array.isArray(p) ? p : p.results ?? []);
        setProviders(Array.isArray(prov) ? prov : prov.results ?? []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoadingOptions(false));
  }, []);

  // Prefill patient/provider if encounter param is present
  useEffect(() => {
    if (!prefillEncounter) return;
    apiFetch(`/emr/encounters/${prefillEncounter}/`)
      .then((enc: any) => {
        if (enc.patient) setForm(f => ({ ...f, patient_id: enc.patient }));
      })
      .catch(() => {});
  }, [prefillEncounter]);

  const setField = (key: string, value: string) => setForm(f => ({ ...f, [key]: value }));

  const addItem = () => setItems(i => [...i, emptyItem()]);
  const removeItem = (idx: number) => setItems(i => i.filter((_, ii) => ii !== idx));
  const updateItem = <K extends keyof GuideItem>(idx: number, key: K, value: GuideItem[K]) =>
    setItems(i => i.map((item, ii) => ii === idx ? { ...item, [key]: value } : item));

  // When TUSS code is selected, auto-fill description from it
  const handleTUSSSelect = (idx: number, opt: TUSSOption | null) => {
    setItems(i => i.map((item, ii) => {
      if (ii !== idx) return item;
      return {
        ...item,
        tuss_code: opt,
        description: opt ? opt.description.slice(0, 300) : item.description,
      };
    }));
  };

  const handleAISuggestionSelect = (idx: number, suggestion: TUSSSuggestion) => {
    setItems(i => i.map((item, ii) => {
      if (ii !== idx) return item;
      return {
        ...item,
        tuss_code: { id: suggestion.tuss_code_id, code: suggestion.tuss_code, description: suggestion.description },
        description: suggestion.description.slice(0, 300),
      };
    }));
  };

  const itemTotal = (item: GuideItem) => {
    const val = parseFloat(item.unit_value || '0');
    return isNaN(val) ? 0 : val * item.quantity;
  };

  const grandTotal = items.reduce((s, i) => s + itemTotal(i), 0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.patient_id || !form.provider_id) { setError('Paciente e operadora são obrigatórios.'); return; }
    if (items.some(i => !i.tuss_code)) { setError('Todos os procedimentos precisam de um código TUSS.'); return; }
    if (items.some(i => !i.unit_value || parseFloat(i.unit_value) <= 0)) {
      setError('Todos os procedimentos precisam de valor unitário maior que zero.');
      return;
    }
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); return; }
    setSaving(true);
    setError('');
    try {
      const body: any = {
        patient: form.patient_id,
        provider: form.provider_id,
        insured_card_number: form.insured_card_number,
        competency: form.competency,
        guide_type: form.guide_type,
        items: items.map(i => ({
          tuss_code: i.tuss_code!.id,
          description: i.description,
          quantity: i.quantity,
          unit_value: i.unit_value,
        })),
      };
      if (form.encounter_id) body.encounter = form.encounter_id;
      const res = await fetch('/api/v1/billing/guides/', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? JSON.stringify(data) ?? `${res.status}`);
      }
      const guide = await res.json();
      router.push(`/billing/guides/${guide.id}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const fmtBRL = (n: number) => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => router.back()} className="text-gray-400 hover:text-gray-600 text-sm">← Voltar</button>
        <h1 className="text-2xl font-semibold text-gray-900">Nova Guia TISS</h1>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Left: form */}
          <div className="flex-1 space-y-5">

            {/* Encontro */}
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
              <h2 className="font-semibold text-gray-900">Encontro</h2>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">ID do Encontro (opcional)</label>
                <input
                  type="text"
                  value={form.encounter_id}
                  onChange={e => setField('encounter_id', e.target.value)}
                  placeholder="UUID do encontro..."
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
            </div>

            {/* Paciente */}
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
              <h2 className="font-semibold text-gray-900">Paciente</h2>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Paciente *</label>
                {loadingOptions ? (
                  <div className="h-9 bg-gray-100 rounded animate-pulse" />
                ) : (
                  <select
                    value={form.patient_id}
                    onChange={e => setField('patient_id', e.target.value)}
                    required
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                  >
                    <option value="">Selecione o paciente...</option>
                    {patients.map(p => (
                      <option key={p.id} value={p.id}>{p.full_name} — {p.medical_record_number ?? p.id}</option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            {/* Convênio */}
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
              <h2 className="font-semibold text-gray-900">Convênio</h2>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Operadora *</label>
                  {loadingOptions ? (
                    <div className="h-9 bg-gray-100 rounded animate-pulse" />
                  ) : (
                    <select
                      value={form.provider_id}
                      onChange={e => setField('provider_id', e.target.value)}
                      required
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                    >
                      <option value="">Selecione a operadora...</option>
                      {providers.map(p => (
                        <option key={p.id} value={p.id}>{p.name ?? p.provider_name ?? p.id}</option>
                      ))}
                    </select>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Nº Carteirinha</label>
                  <input
                    type="text"
                    value={form.insured_card_number}
                    onChange={e => setField('insured_card_number', e.target.value)}
                    placeholder="000000000000000"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Competência (AAAA-MM)</label>
                  <input
                    type="text"
                    value={form.competency}
                    onChange={e => setField('competency', e.target.value)}
                    placeholder="2024-03"
                    pattern="\d{4}-\d{2}"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Tipo de Guia</label>
                  <select
                    value={form.guide_type}
                    onChange={e => setField('guide_type', e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                  >
                    <option value="sadt">SADT</option>
                    <option value="consulta">Consulta</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Procedimentos */}
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-gray-900">Procedimentos</h2>
                <button type="button" onClick={addItem} className="text-sm text-blue-600 hover:underline">
                  + Adicionar
                </button>
              </div>

              {items.map((item, idx) => (
                <div key={idx} className="border border-gray-100 rounded-lg p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Item {idx + 1}</span>
                    {items.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeItem(idx)}
                        className="text-red-400 hover:text-red-600 text-xs"
                      >
                        Remover
                      </button>
                    )}
                  </div>

                  {/* TUSS code */}
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Código TUSS *</label>
                    <TUSSCodeSearch
                      value={item.tuss_code}
                      onChange={opt => handleTUSSSelect(idx, opt)}
                    />
                  </div>

                  {/* Description + AI suggestion */}
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Descrição</label>
                    <input
                      type="text"
                      value={item.description}
                      onChange={e => updateItem(idx, 'description', e.target.value)}
                      placeholder="Descrição do procedimento..."
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                    <TUSSSuggestionInline
                      description={item.description}
                      guideType={form.guide_type}
                      onSelect={suggestion => handleAISuggestionSelect(idx, suggestion)}
                      hasExistingCode={!!item.tuss_code}
                    />
                  </div>

                  {/* Qty + unit value */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Quantidade</label>
                      <input
                        type="number"
                        min={1}
                        step="0.01"
                        value={item.quantity}
                        onChange={e => updateItem(idx, 'quantity', Number(e.target.value))}
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Valor Unitário (R$) *</label>
                      <input
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={item.unit_value}
                        onChange={e => updateItem(idx, 'unit_value', e.target.value)}
                        placeholder="0,00"
                        className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                      />
                    </div>
                  </div>

                  {/* Item subtotal */}
                  {item.unit_value && (
                    <div className="text-right text-xs text-gray-500">
                      Subtotal: <span className="font-medium text-gray-800">{fmtBRL(itemTotal(item))}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Right: summary */}
          <div className="lg:w-72 space-y-4">
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3 sticky top-6">
              <h2 className="font-semibold text-gray-900">Resumo</h2>
              <div className="text-sm space-y-2 text-gray-600">
                <div className="flex justify-between">
                  <span>Paciente</span>
                  <span className="text-gray-900 font-medium text-right max-w-[140px] truncate">
                    {patients.find(p => p.id === form.patient_id)?.full_name ?? '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Operadora</span>
                  <span className="text-gray-900 font-medium text-right max-w-[140px] truncate">
                    {providers.find(p => p.id === form.provider_id)?.name ?? '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Tipo</span>
                  <span className="text-gray-900 font-medium">{form.guide_type === 'sadt' ? 'SADT' : 'Consulta'}</span>
                </div>
                <div className="flex justify-between">
                  <span>Competência</span>
                  <span className="text-gray-900 font-medium">{form.competency || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span>Procedimentos</span>
                  <span className="text-gray-900 font-medium">{items.length} item(s)</span>
                </div>
              </div>
              {grandTotal > 0 && (
                <div className="pt-3 border-t border-gray-100">
                  <div className="flex justify-between text-sm font-semibold">
                    <span>Total</span>
                    <span className="text-blue-700">{fmtBRL(grandTotal)}</span>
                  </div>
                </div>
              )}
              <div className="pt-3 border-t border-gray-100 space-y-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="w-full bg-blue-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Criando...' : 'Criar Guia'}
                </button>
                <button
                  type="button"
                  onClick={() => router.back()}
                  className="w-full text-gray-600 py-2 rounded-lg text-sm hover:text-gray-800"
                >
                  Cancelar
                </button>
              </div>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
