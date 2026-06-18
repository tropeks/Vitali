'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ClipboardList,
  FileText,
  Plus,
  Receipt,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { PageShell, ReadinessPanel } from '@/components/shared';
import TUSSCodeSearch, { TUSSOption } from '@/components/billing/TUSSCodeSearch';
import TUSSSuggestionInline, { TUSSSuggestion } from '@/components/billing/TUSSSuggestionInline';
import GlosaRiskBadge from '@/components/billing/GlosaRiskBadge';

interface PatientOption {
  id: string | number;
  full_name?: string;
  medical_record_number?: string;
  age?: number;
  birth_date?: string;
  active_allergies_count?: number;
}

interface ProviderOption {
  id: string | number;
  name?: string;
  provider_name?: string;
  ans_code?: string;
  cnpj?: string;
}

interface EncounterContext {
  id: string;
  patient?: string;
  patient_name?: string;
  patient_mrn?: string;
  professional_name?: string;
  status?: string;
  status_display?: string;
  chief_complaint?: string;
  started_at?: string;
}

interface GuideItem {
  tuss_code: TUSSOption | null;
  description: string;
  quantity: number;
  unit_value: string;
}

interface FormState {
  encounter_id: string;
  patient_id: string;
  provider_id: string;
  insured_card_number: string;
  competency: string;
  guide_type: string;
}

const emptyItem = (): GuideItem => ({ tuss_code: null, description: '', quantity: 1, unit_value: '' });

function apiFetch<T>(path: string): Promise<T> {
  const token = getAccessToken();
  if (!token) return Promise.reject(new Error('Sessão expirada'));
  return fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then((r) => {
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  });
}

function listFromResponse<T>(data: T[] | { results?: T[] }): T[] {
  return Array.isArray(data) ? data : data.results ?? [];
}

function providerName(provider?: ProviderOption) {
  return provider?.name ?? provider?.provider_name ?? 'Operadora não selecionada';
}

function sameId(left: string | number | undefined, right: string | number | undefined) {
  return left !== undefined && right !== undefined && String(left) === String(right);
}

function patientName(patient?: PatientOption, encounter?: EncounterContext | null) {
  return patient?.full_name ?? encounter?.patient_name ?? 'Paciente não selecionado';
}

function patientMrn(patient?: PatientOption, encounter?: EncounterContext | null) {
  return patient?.medical_record_number ?? encounter?.patient_mrn ?? 'MRN pendente';
}

function itemTotal(item: GuideItem) {
  const val = Number.parseFloat(item.unit_value || '0');
  return Number.isFinite(val) ? val * item.quantity : 0;
}

function fmtBRL(n: number) {
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function itemBlockers(item: GuideItem) {
  const blockers: string[] = [];
  if (!item.tuss_code) blockers.push('TUSS');
  if (!item.unit_value || Number.parseFloat(item.unit_value) <= 0) blockers.push('valor');
  if (!item.quantity || item.quantity <= 0) blockers.push('quantidade');
  return blockers;
}

function readinessBlockers(form: FormState, items: GuideItem[]) {
  const blockers: string[] = [];
  if (!form.patient_id) blockers.push('Selecionar paciente');
  if (!form.provider_id) blockers.push('Selecionar operadora');
  if (items.some((item) => !item.tuss_code)) blockers.push('Completar códigos TUSS');
  if (items.some((item) => !item.unit_value || Number.parseFloat(item.unit_value) <= 0)) {
    blockers.push('Informar valores unitários');
  }
  if (items.some((item) => !item.quantity || item.quantity <= 0)) blockers.push('Revisar quantidades');
  return blockers;
}

export default function NewGuidePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const prefillEncounter = searchParams.get('encounter') ?? '';

  const [patients, setPatients] = useState<PatientOption[]>([]);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [encounterContext, setEncounterContext] = useState<EncounterContext | null>(null);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [loadingEncounter, setLoadingEncounter] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [form, setForm] = useState<FormState>({
    encounter_id: prefillEncounter,
    patient_id: '',
    provider_id: '',
    insured_card_number: '',
    competency: new Date().toISOString().slice(0, 7),
    guide_type: 'sadt',
  });

  const [items, setItems] = useState<GuideItem[]>([emptyItem()]);
  const [glosaPredictionIds, setGlosaPredictionIds] = useState<Record<number, string | null>>({});

  useEffect(() => {
    Promise.all([
      apiFetch<PatientOption[] | { results?: PatientOption[] }>('/patients/?page_size=200'),
      apiFetch<ProviderOption[] | { results?: ProviderOption[] }>('/billing/providers/'),
    ])
      .then(([patientData, providerData]) => {
        setPatients(listFromResponse(patientData));
        setProviders(listFromResponse(providerData));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingOptions(false));
  }, []);

  useEffect(() => {
    if (!prefillEncounter) return;
    setLoadingEncounter(true);
    apiFetch<EncounterContext>(`/encounters/${prefillEncounter}/`)
      .then((enc) => {
        setEncounterContext(enc);
        const patientId = enc.patient;
        if (typeof patientId === 'string' && patientId) {
          setForm((f) => ({ ...f, patient_id: patientId }));
        }
      })
      .catch(() => {
        setEncounterContext(null);
      })
      .finally(() => setLoadingEncounter(false));
  }, [prefillEncounter]);

  const setField = (key: keyof FormState, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
  };

  const addItem = () => setItems((i) => [...i, emptyItem()]);

  const removeItem = (idx: number) => {
    setItems((i) => i.filter((_, ii) => ii !== idx));
    setGlosaPredictionIds((prev) => {
      const next: Record<number, string | null> = {};
      Object.entries(prev).forEach(([k, v]) => {
        const n = Number(k);
        if (n < idx) next[n] = v;
        else if (n > idx) next[n - 1] = v;
      });
      return next;
    });
  };

  const updateItem = <K extends keyof GuideItem>(idx: number, key: K, value: GuideItem[K]) => {
    setItems((current) => current.map((item, ii) => (ii === idx ? { ...item, [key]: value } : item)));
  };

  const selectedPatient = patients.find((p) => sameId(p.id, form.patient_id));
  const selectedProvider = providers.find((p) => sameId(p.id, form.provider_id));
  const insurerAnsCode = selectedProvider?.ans_code ?? null;
  const grandTotal = items.reduce((sum, item) => sum + itemTotal(item), 0);
  const blockers = useMemo(() => readinessBlockers(form, items), [form, items]);
  const ready = blockers.length === 0;
  const predictedCount = Object.values(glosaPredictionIds).filter(Boolean).length;

  const handleTUSSSelect = (idx: number, opt: TUSSOption | null) => {
    setItems((current) => current.map((item, ii) => {
      if (ii !== idx) return item;
      return {
        ...item,
        tuss_code: opt,
        description: opt ? opt.description.slice(0, 300) : item.description,
      };
    }));
  };

  const handleAISuggestionSelect = (idx: number, suggestion: TUSSSuggestion) => {
    setItems((current) => current.map((item, ii) => {
      if (ii !== idx) return item;
      return {
        ...item,
        tuss_code: {
          id: suggestion.tuss_code_id,
          code: suggestion.tuss_code,
          description: suggestion.description,
        },
        description: suggestion.description.slice(0, 300),
      };
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const currentBlockers = readinessBlockers(form, items);
    if (currentBlockers.length > 0) {
      setError(`Pendências antes de criar a guia: ${currentBlockers.join(', ')}.`);
      return;
    }

    const token = getAccessToken();
    if (!token) {
      setError('Sessão expirada');
      return;
    }

    setSaving(true);
    setError('');
    try {
      const predictionIds = Object.values(glosaPredictionIds).filter((id): id is string => !!id);
      const body: any = {
        patient: form.patient_id,
        provider: form.provider_id,
        insured_card_number: form.insured_card_number,
        competency: form.competency,
        guide_type: form.guide_type,
        glosa_prediction_ids: predictionIds,
        items: items.map((item) => ({
          tuss_code: item.tuss_code!.id,
          description: item.description,
          quantity: item.quantity,
          unit_value: item.unit_value,
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

  return (
    <PageShell variant="workbench">
        <header className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => router.back()}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-[#F4F7FA] text-[#8C959F] hover:bg-[#DFE5EB] focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Voltar"
          >
            <ArrowLeft size={16} />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold text-[#24292F]">Bancada TISS</h1>
            <p className="text-sm text-[#8C959F]">
              Guia, contexto clínico, TUSS, glosa e total em uma única superfície de faturamento.
            </p>
          </div>
          <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${
            ready
              ? 'border-green-200 bg-green-50 text-green-700'
              : 'border-yellow-200 bg-yellow-50 text-yellow-800'
          }`}>
            {ready ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {ready ? 'Pronta para criar' : `${blockers.length} pendência(s)`}
          </span>
        </header>

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <ClipboardList size={14} />
              Atendimento
            </div>
            <p className="mt-2 truncate text-sm font-semibold text-[#24292F]">
              {loadingEncounter ? 'Carregando atendimento...' : encounterContext?.status_display ?? encounterContext?.status ?? 'Guia avulsa'}
            </p>
            <p className="mt-1 truncate font-mono text-xs text-[#8C959F]">
              {form.encounter_id || 'Sem atendimento vinculado'}
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <FileText size={14} />
              Paciente
            </div>
            <p className="mt-2 truncate text-sm font-semibold text-[#24292F]">
              {patientName(selectedPatient, encounterContext)}
            </p>
            <p className="mt-1 truncate font-mono text-xs text-[#8C959F]">
              {patientMrn(selectedPatient, encounterContext)}
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <Receipt size={14} />
              Operadora
            </div>
            <p className="mt-2 truncate text-sm font-semibold text-[#24292F]">
              {providerName(selectedProvider)}
            </p>
            <p className="mt-1 truncate font-mono text-xs text-[#8C959F]">
              {selectedProvider?.ans_code ? `ANS ${selectedProvider.ans_code}` : 'ANS pendente'}
            </p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <ShieldCheck size={14} />
              Glosa / IA
            </div>
            <p className="mt-2 text-sm font-semibold text-[#24292F]">
              {predictedCount}/{items.length} item(ns) avaliados
            </p>
            <p className="mt-1 text-xs text-[#8C959F]">Sugestão TUSS e risco inline</p>
          </div>
        </section>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="space-y-4">
              <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
                <div className="border-b border-slate-100 px-4 py-3">
                  <h2 className="text-base font-semibold text-[#24292F]">Contexto da guia</h2>
                </div>
                <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
                  <div>
                    <label htmlFor="guide-patient" className="mb-1 block text-xs font-medium text-[#57606A]">Paciente *</label>
                    {loadingOptions ? (
                      <div className="h-9 animate-pulse rounded-lg bg-[#DFE5EB]" />
                    ) : (
                      <select
                        id="guide-patient"
                        value={form.patient_id}
                        onChange={(e) => setField('patient_id', e.target.value)}
                        required
                        className="w-full rounded-lg border border-slate-200 bg-[#F4F7FA] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">Selecionar paciente</option>
                        {patients.map((patient) => (
                          <option key={patient.id} value={patient.id}>
                            {patient.full_name} - {patient.medical_record_number ?? patient.id}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  <div>
                    <label htmlFor="guide-provider" className="mb-1 block text-xs font-medium text-[#57606A]">Operadora *</label>
                    {loadingOptions ? (
                      <div className="h-9 animate-pulse rounded-lg bg-[#DFE5EB]" />
                    ) : (
                      <select
                        id="guide-provider"
                        value={form.provider_id}
                        onChange={(e) => setField('provider_id', e.target.value)}
                        required
                        className="w-full rounded-lg border border-slate-200 bg-[#F4F7FA] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">Selecionar operadora</option>
                        {providers.map((provider) => (
                          <option key={provider.id} value={provider.id}>
                            {providerName(provider)}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  <div>
                    <label htmlFor="guide-card-number" className="mb-1 block text-xs font-medium text-[#57606A]">Carteirinha</label>
                    <input
                      id="guide-card-number"
                      type="text"
                      value={form.insured_card_number}
                      onChange={(e) => setField('insured_card_number', e.target.value)}
                      placeholder="Número da carteirinha"
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label htmlFor="guide-competency" className="mb-1 block text-xs font-medium text-[#57606A]">Competência</label>
                    <input
                      id="guide-competency"
                      type="month"
                      value={form.competency}
                      onChange={(e) => setField('competency', e.target.value)}
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label htmlFor="guide-type" className="mb-1 block text-xs font-medium text-[#57606A]">Tipo de guia</label>
                    <select
                      id="guide-type"
                      value={form.guide_type}
                      onChange={(e) => setField('guide_type', e.target.value)}
                      className="w-full rounded-lg border border-slate-200 bg-[#F4F7FA] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="sadt">SADT</option>
                      <option value="consulta">Consulta</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="guide-encounter" className="mb-1 block text-xs font-medium text-[#57606A]">Atendimento vinculado</label>
                    <input
                      id="guide-encounter"
                      type="text"
                      value={form.encounter_id}
                      onChange={(e) => setField('encounter_id', e.target.value)}
                      placeholder="Vincular por ID quando necessário"
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm outline-none placeholder:font-sans placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
                <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-base font-semibold text-[#24292F]">Procedimentos e riscos</h2>
                    <p className="text-xs text-[#8C959F]">Cada linha precisa sair com TUSS, preço e status de glosa visíveis.</p>
                  </div>
                  <button
                    type="button"
                    onClick={addItem}
                    className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-b from-[#0066A1] to-[#005282] border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] px-3 py-2 text-sm font-medium text-white hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <Plus size={16} />
                    Adicionar item
                  </button>
                </div>

                <div className="hidden grid-cols-[76px_minmax(0,1fr)_68px_92px_92px_36px] gap-3 border-b border-slate-100 px-4 py-2 text-xs font-semibold uppercase text-slate-400 lg:grid">
                  <span>Status</span>
                  <span>Procedimento / TUSS / IA</span>
                  <span>Qtd.</span>
                  <span>Valor</span>
                  <span>Total</span>
                  <span />
                </div>

                <div className="divide-y divide-slate-100">
                  {items.map((item, idx) => {
                    const missing = itemBlockers(item);
                    const itemReady = missing.length === 0;
                    return (
                      <div
                        key={idx}
                        className="grid gap-3 px-4 py-3 lg:grid-cols-[76px_minmax(0,1fr)_68px_92px_92px_36px] lg:items-start"
                      >
                        <div className="min-w-0">
                          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${
                            itemReady
                              ? 'border-green-200 bg-green-50 text-green-700'
                              : 'border-yellow-200 bg-yellow-50 text-yellow-800'
                          }`}>
                            {itemReady ? 'Pronto' : `Falta ${missing.join('/')}`}
                          </span>
                          <p className="mt-1 text-xs text-slate-400">Item {idx + 1}</p>
                        </div>

                        <div className="min-w-0 space-y-2">
                          <label className="mb-1 block text-xs font-medium text-[#8C959F] lg:hidden">Código TUSS *</label>
                          <TUSSCodeSearch
                            value={item.tuss_code}
                            onChange={(opt) => handleTUSSSelect(idx, opt)}
                            placeholder="Buscar por código ou procedimento"
                          />
                          <GlosaRiskBadge
                            tussCode={item.tuss_code?.code ?? null}
                            insurerAnsCode={insurerAnsCode}
                            insurerName={providerName(selectedProvider)}
                            guideType={form.guide_type}
                            onPrediction={(predId) => setGlosaPredictionIds((prev) => ({ ...prev, [idx]: predId }))}
                          />
                          <label htmlFor={`guide-item-description-${idx}`} className="mb-1 block text-xs font-medium text-[#8C959F] lg:hidden">Descrição</label>
                          <input
                            id={`guide-item-description-${idx}`}
                            type="text"
                            value={item.description}
                            onChange={(e) => updateItem(idx, 'description', e.target.value)}
                            placeholder="Descrição do procedimento"
                            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500"
                          />
                          <div className="mt-1 flex items-center gap-1.5 text-xs text-slate-400">
                            <Bot size={13} />
                            <span>IA sugere TUSS a partir da descrição</span>
                          </div>
                          <TUSSSuggestionInline
                            description={item.description}
                            guideType={form.guide_type}
                            onSelect={(suggestion) => handleAISuggestionSelect(idx, suggestion)}
                            hasExistingCode={!!item.tuss_code}
                          />
                        </div>

                        <div className="min-w-0">
                          <label htmlFor={`guide-item-quantity-${idx}`} className="mb-1 block text-xs font-medium text-[#8C959F] lg:hidden">Quantidade</label>
                          <input
                            id={`guide-item-quantity-${idx}`}
                            type="number"
                            min={1}
                            step="0.01"
                            value={item.quantity}
                            onChange={(e) => updateItem(idx, 'quantity', Number(e.target.value || 0))}
                            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div className="min-w-0">
                          <label htmlFor={`guide-item-unit-value-${idx}`} className="mb-1 block text-xs font-medium text-[#8C959F] lg:hidden">Valor unitário</label>
                          <input
                            id={`guide-item-unit-value-${idx}`}
                            type="number"
                            min="0.01"
                            step="0.01"
                            value={item.unit_value}
                            onChange={(e) => updateItem(idx, 'unit_value', e.target.value)}
                            placeholder="0,00"
                            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div>
                          <span className="block text-xs font-medium text-[#8C959F] lg:hidden">Total</span>
                          <p className="rounded-lg bg-[#F4F7FA] px-3 py-2 text-sm font-semibold text-[#24292F]">
                            {fmtBRL(itemTotal(item))}
                          </p>
                        </div>

                        <div className="flex justify-end">
                          {items.length > 1 && (
                            <button
                              type="button"
                              onClick={() => removeItem(idx)}
                              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-red-500 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500"
                              aria-label={`Remover item ${idx + 1}`}
                            >
                              <Trash2 size={16} />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>

            <aside className="space-y-4">
              <div className="sticky top-4 rounded-lg border border-slate-200 bg-[#F4F7FA]">
                <div className="border-b border-slate-100 px-4 py-3">
                  <h2 className="text-base font-semibold text-[#24292F]">Fechamento</h2>
                  <p className="text-xs text-[#8C959F]">Resumo operacional antes da criação da guia.</p>
                </div>
                <div className="space-y-4 p-4">
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-[#8C959F]">Paciente</span>
                      <span className="max-w-[190px] truncate text-right font-medium text-[#24292F]">
                        {patientName(selectedPatient, encounterContext)}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-[#8C959F]">Operadora</span>
                      <span className="max-w-[190px] truncate text-right font-medium text-[#24292F]">
                        {providerName(selectedProvider)}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-[#8C959F]">Tipo</span>
                      <span className="font-medium text-[#24292F]">{form.guide_type === 'sadt' ? 'SADT' : 'Consulta'}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-[#8C959F]">Competência</span>
                      <span className="font-medium text-[#24292F]">{form.competency || '-'}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-[#8C959F]">Procedimentos</span>
                      <span className="font-medium text-[#24292F]">{items.length}</span>
                    </div>
                  </div>

                  <div className="rounded-lg bg-blue-50 p-4">
                    <p className="text-xs font-semibold uppercase text-blue-700">Total da guia</p>
                    <p className="mt-1 text-2xl font-bold text-blue-900">{fmtBRL(grandTotal)}</p>
                  </div>

                  <ReadinessPanel
                    blockers={blockers}
                    readyText="Sem bloqueios. A guia pode ser criada."
                  />

                  <button
                    type="submit"
                    disabled={saving}
                    className="w-full rounded-lg bg-gradient-to-b from-[#0066A1] to-[#005282] border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] py-2.5 text-sm font-semibold text-white hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {saving ? 'Criando guia...' : 'Criar guia TISS'}
                  </button>
                  <button
                    type="button"
                    onClick={() => router.back()}
                    className="w-full rounded-lg py-2 text-sm font-medium text-[#57606A] hover:bg-[#F4F7FA] focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            </aside>
          </div>
        </form>
    </PageShell>
  );
}
