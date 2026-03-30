'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';

function apiFetch(path: string) {
  const token = getAccessToken();
  if (!token) return Promise.reject(new Error('Sessão expirada'));
  return fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); });
}

interface Item {
  quantity: number;
  description: string;
}

export default function NewGuidePage() {
  const router = useRouter();
  const [patients, setPatients] = useState<any[]>([]);
  const [providers, setProviders] = useState<any[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [form, setForm] = useState({
    encounter_id: '',
    patient_id: '',
    provider_id: '',
    insured_card_number: '',
    competency: '',
    guide_type: 'sadt',
  });

  const [items, setItems] = useState<Item[]>([{ quantity: 1, description: '' }]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { setError('Sessão expirada'); setLoadingOptions(false); return; }
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

  const setField = (key: string, value: string) => setForm(f => ({ ...f, [key]: value }));

  const addItem = () => setItems(i => [...i, { quantity: 1, description: '' }]);
  const removeItem = (idx: number) => setItems(i => i.filter((_, ii) => ii !== idx));
  const updateItem = (idx: number, key: keyof Item, value: any) =>
    setItems(i => i.map((item, ii) => ii === idx ? { ...item, [key]: value } : item));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.patient_id || !form.provider_id) { setError('Paciente e operadora são obrigatórios.'); return; }
    if (items.some(i => !i.description)) { setError('Todos os procedimentos precisam de descrição.'); return; }
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
        items,
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

  const totalItems = items.reduce((s, i) => s + i.quantity, 0);

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
            </div>

            {/* Detalhes TISS */}
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
              <h2 className="font-semibold text-gray-900">Detalhes TISS</h2>
              <div className="grid grid-cols-2 gap-4">
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

            {/* Procedimentos */}
            <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold text-gray-900">Procedimentos</h2>
                <button
                  type="button"
                  onClick={addItem}
                  className="text-sm text-blue-600 hover:underline"
                >
                  + Adicionar
                </button>
              </div>
              {items.map((item, idx) => (
                <div key={idx} className="flex gap-3 items-start">
                  <div className="w-20">
                    <label className="block text-xs text-gray-500 mb-1">Qtd</label>
                    <input
                      type="number"
                      min={1}
                      value={item.quantity}
                      onChange={e => updateItem(idx, 'quantity', Number(e.target.value))}
                      className="w-full border border-gray-200 rounded-lg px-2 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="block text-xs text-gray-500 mb-1">Descrição *</label>
                    <input
                      type="text"
                      value={item.description}
                      onChange={e => updateItem(idx, 'description', e.target.value)}
                      placeholder="Ex: Consulta médica, Raio-X..."
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                  </div>
                  {items.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeItem(idx)}
                      className="mt-5 text-red-400 hover:text-red-600 text-xs"
                    >
                      Remover
                    </button>
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
                    {providers.find(p => p.id === form.provider_id)?.name ?? providers.find(p => p.id === form.provider_id)?.provider_name ?? '—'}
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
                  <span className="text-gray-900 font-medium">{items.length} item(s) / {totalItems} qtd</span>
                </div>
              </div>
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
