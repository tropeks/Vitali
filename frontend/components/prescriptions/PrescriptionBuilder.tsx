'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  AlertTriangle,
  ClipboardPlus,
  FileText,
  Loader2,
  Pill,
  Plus,
  Printer,
  Search,
  Trash2,
} from 'lucide-react';
import { getAccessToken } from '@/lib/auth';
import { SafetyBadge } from './SafetyBadge';
import { SafetyAlertModal } from './SafetyAlertModal';
import type { SafetyAlert } from './SafetyBadge';

interface Drug {
  id: string;
  name: string;
  generic_name: string;
  is_controlled: boolean;
}

interface PrescriptionItem {
  id: string;
  drug: string;
  drug_name: string;
  drug_generic_name: string;
  drug_is_controlled: boolean;
  generic_name: string;
  quantity: string;
  unit_of_measure: string;
  dosage_instructions: string;
  notes: string;
}

interface Prescription {
  id: string;
  encounter: string;
  status: string;
  status_display: string;
  is_signed: boolean;
  signed_at: string | null;
  prescriber_name: string;
  notes: string;
  items: PrescriptionItem[];
  created_at: string;
}

interface PrescriptionBuilderProps {
  encounterId: string;
  readOnly?: boolean;
}

interface ApiList<T> {
  results?: T[];
}

const PRESCRIPTION_STATUS_STYLES: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700 border-slate-200',
  active: 'bg-blue-100 text-blue-800 border-blue-200',
  signed: 'bg-green-100 text-green-800 border-green-200',
  cancelled: 'bg-red-100 text-red-700 border-red-200',
};

const ORDER_PRESETS = [
  {
    label: 'Dor/febre',
    search: 'dipirona',
    quantity: '1',
    unit: 'ampola',
    dosage: 'Dipirona 1g EV/VO a cada 6h se dor ou febre',
  },
  {
    label: 'Náusea',
    search: 'ondansetrona',
    quantity: '1',
    unit: 'ampola',
    dosage: 'Ondansetrona 4mg EV a cada 8h se náusea',
  },
  {
    label: 'Hidratação',
    search: 'soro fisiologico',
    quantity: '500',
    unit: 'ml',
    dosage: 'SF 0,9% 500ml EV em 2h, conforme avaliação clínica',
  },
];

const defaultItemForm = {
  quantity: '1',
  unit_of_measure: 'cp',
  dosage_instructions: '',
  dose_amount: '',
  dose_unit: '',
  route: '',
  frequency_per_day: '',
};

const DOSE_UNIT_OPTIONS = ['mg', 'mcg', 'mEq', 'unit', 'g'];

const ROUTE_OPTIONS: { value: string; label: string }[] = [
  { value: 'IV', label: 'Intravenosa' },
  { value: 'IM', label: 'Intramuscular' },
  { value: 'SC', label: 'Subcutânea' },
  { value: 'PO', label: 'Oral' },
];

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const message =
      typeof data.error === 'string'
        ? data.error
        : typeof data.detail === 'string'
          ? data.detail
          : `Erro ${res.status}`;
    throw new Error(message);
  }
  return res.json();
}

function asList<T>(data: ApiList<T> | T[]): T[] {
  return Array.isArray(data) ? data : data.results ?? [];
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function OrderSafetyBadge({ prescriptionId, itemId }: { prescriptionId: string; itemId: string }) {
  const [alertsToShow, setAlertsToShow] = useState<SafetyAlert[] | null>(null);

  return (
    <>
      <SafetyBadge
        prescriptionId={prescriptionId}
        itemId={itemId}
        onAlertsClick={alerts => setAlertsToShow(alerts)}
      />
      {alertsToShow && (
        <SafetyAlertModal
          alerts={alertsToShow}
          onClose={() => setAlertsToShow(null)}
        />
      )}
    </>
  );
}

function OrderGridRow({
  item,
  prescriptionId,
  prescriptionStatus,
  readOnly,
  onRemove,
}: {
  item: PrescriptionItem;
  prescriptionId: string;
  prescriptionStatus: string;
  readOnly: boolean;
  onRemove: (id: string) => void;
}) {
  return (
    <div className="grid gap-2 border-t border-slate-100 px-3 py-3 text-sm lg:grid-cols-[minmax(220px,1.3fr)_80px_96px_minmax(220px,1fr)_140px_112px_88px] lg:items-center">
      <div className="min-w-0">
        <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-400 lg:hidden">
          Medicamento
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-semibold text-slate-900">{item.drug_name}</span>
          {item.drug_is_controlled && (
            <span className="rounded-full border border-orange-200 bg-orange-50 px-2 py-0.5 text-xs font-semibold text-orange-700">
              Controlado
            </span>
          )}
        </div>
        {item.drug_generic_name && item.drug_generic_name !== item.drug_name && (
          <p className="mt-0.5 truncate text-xs text-slate-500">{item.drug_generic_name}</p>
        )}
      </div>

      <div>
        <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-400 lg:hidden">
          Quantidade
        </span>
        <span className="font-mono text-slate-800">{item.quantity}</span>
      </div>

      <div>
        <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-400 lg:hidden">
          Unidade
        </span>
        <span className="text-slate-700">{item.unit_of_measure}</span>
      </div>

      <div className="min-w-0">
        <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-400 lg:hidden">
          Posologia
        </span>
        <span className="text-slate-800">{item.dosage_instructions || 'Não informada'}</span>
      </div>

      <div>
        <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-400 lg:hidden">
          Segurança
        </span>
        <OrderSafetyBadge prescriptionId={prescriptionId} itemId={item.id} />
      </div>

      <div>
        <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wide text-slate-400 lg:hidden">
          Status
        </span>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-700">
          {prescriptionStatus}
        </span>
      </div>

      <div className="flex justify-start lg:justify-end">
        {!readOnly && (
          <button
            onClick={() => onRemove(item.id)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-50 hover:text-red-700"
            aria-label={`Remover ${item.drug_name}`}
          >
            <Trash2 size={13} />
            Remover
          </button>
        )}
      </div>
    </div>
  );
}

function StatusStripItem({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="bg-white px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-lg font-bold text-slate-950">{value}</p>
      <p className="text-xs text-slate-500">{detail}</p>
    </div>
  );
}

export function PrescriptionBuilder({ encounterId, readOnly = false }: PrescriptionBuilderProps) {
  const [prescriptions, setPrescriptions] = useState<Prescription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingRx, setCreatingRx] = useState(false);
  const [printingId, setPrintingId] = useState<string | null>(null);
  const [drugSearch, setDrugSearch] = useState('');
  const [drugResults, setDrugResults] = useState<Drug[]>([]);
  const [searching, setSearching] = useState(false);
  const [activePrescriptionId, setActivePrescriptionId] = useState<string | null>(null);
  const [addingItem, setAddingItem] = useState(false);
  const [newItemForm, setNewItemForm] = useState(defaultItemForm);
  const [selectedDrug, setSelectedDrug] = useState<Drug | null>(null);

  const loadPrescriptions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<ApiList<Prescription> | Prescription[]>(
        `/prescriptions/?encounter=${encounterId}`
      );
      setPrescriptions(asList(data));
    } catch (e) {
      setPrescriptions([]);
      setError(e instanceof Error ? e.message : 'Não foi possível carregar prescrições.');
    } finally {
      setLoading(false);
    }
  }, [encounterId]);

  useEffect(() => { loadPrescriptions(); }, [loadPrescriptions]);

  const createPrescription = async () => {
    setCreatingRx(true);
    setError(null);
    try {
      const rx = await apiFetch<Prescription>('/prescriptions/', {
        method: 'POST',
        body: JSON.stringify({ encounter: encounterId }),
      });
      const next = { ...rx, items: rx.items ?? [] };
      setPrescriptions(prev => [next, ...prev]);
      setActivePrescriptionId(rx.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao criar prescrição.');
    } finally {
      setCreatingRx(false);
    }
  };

  const searchDrugs = async (q: string) => {
    if (!q.trim()) {
      setDrugResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    try {
      const data = await apiFetch<ApiList<Drug> | Drug[]>(`/pharmacy/drugs/?search=${encodeURIComponent(q)}&limit=5`);
      setDrugResults(asList(data));
    } catch {
      setDrugResults([]);
      setError('Busca de medicamentos indisponível no momento.');
    } finally {
      setSearching(false);
    }
  };

  const resetComposer = () => {
    setSelectedDrug(null);
    setDrugSearch('');
    setDrugResults([]);
    setNewItemForm(defaultItemForm);
  };

  const beginAddItem = (prescriptionId: string) => {
    setActivePrescriptionId(prescriptionId);
    resetComposer();
    setError(null);
  };

  const applyPreset = (preset: typeof ORDER_PRESETS[number]) => {
    const editablePrescription = prescriptions.find(rx => !rx.is_signed);
    if (!activePrescriptionId && editablePrescription) {
      setActivePrescriptionId(editablePrescription.id);
    }
    setSelectedDrug(null);
    setDrugSearch(preset.search);
    setNewItemForm({
      ...defaultItemForm,
      quantity: preset.quantity,
      unit_of_measure: preset.unit,
      dosage_instructions: preset.dosage,
    });
    void searchDrugs(preset.search);
  };

  const addItem = async (prescriptionId: string) => {
    if (!selectedDrug) return;
    setAddingItem(true);
    setError(null);
    try {
      const item = await apiFetch<PrescriptionItem>('/prescription-items/', {
        method: 'POST',
        body: JSON.stringify({
          prescription: prescriptionId,
          drug: selectedDrug.id,
          quantity: parseFloat(newItemForm.quantity) || 1,
          unit_of_measure: newItemForm.unit_of_measure,
          dosage_instructions: newItemForm.dosage_instructions,
          // Structured dose fields (optional). Numeric fields must be null when
          // empty — a DecimalField/IntegerField rejects "". CharFields (dose_unit,
          // route) accept "" (blank=True).
          dose_amount: newItemForm.dose_amount.trim() === '' ? null : parseFloat(newItemForm.dose_amount),
          dose_unit: newItemForm.dose_unit,
          route: newItemForm.route,
          frequency_per_day:
            newItemForm.frequency_per_day.trim() === '' ? null : parseInt(newItemForm.frequency_per_day, 10),
        }),
      });
      setPrescriptions(prev =>
        prev.map(rx => rx.id === prescriptionId ? { ...rx, items: [...rx.items, item] } : rx)
      );
      resetComposer();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao adicionar ordem.');
    } finally {
      setAddingItem(false);
    }
  };

  const removeItem = async (prescriptionId: string, itemId: string) => {
    setError(null);
    try {
      await apiFetch(`/prescription-items/${itemId}/`, { method: 'DELETE' });
      setPrescriptions(prev =>
        prev.map(rx => rx.id === prescriptionId
          ? { ...rx, items: rx.items.filter(i => i.id !== itemId) }
          : rx
        )
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erro ao remover ordem.');
    }
  };

  const printPDF = async (prescriptionId: string, isSigned: boolean) => {
    if (!isSigned) {
      setError('A prescrição precisa estar assinada para imprimir.');
      return;
    }
    setPrintingId(prescriptionId);
    setError(null);
    try {
      const token = getAccessToken();
      const res = await fetch(`/api/v1/prescriptions/${prescriptionId}/pdf/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener,noreferrer');
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch {
      setError('Erro ao gerar PDF. Verifique se a prescrição está assinada.');
    } finally {
      setPrintingId(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3" role="status" aria-label="Carregando CPOE">
        <div className="h-16 animate-pulse rounded-lg bg-slate-100" />
        <div className="h-44 animate-pulse rounded-lg bg-slate-100" />
      </div>
    );
  }

  const totalItems = prescriptions.reduce((sum, rx) => sum + rx.items.length, 0);
  const controlledItems = prescriptions.reduce(
    (sum, rx) => sum + rx.items.filter(item => item.drug_is_controlled).length,
    0
  );
  const unsignedPrescriptions = prescriptions.filter(rx => !rx.is_signed).length;
  const hasEditablePrescription = prescriptions.some(rx => !rx.is_signed);

  return (
    <div className="space-y-4">
      <div className="grid gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 md:grid-cols-4">
        <StatusStripItem
          label="Prescrições"
          value={String(prescriptions.length)}
          detail={`${unsignedPrescriptions} pendente(s) de assinatura`}
        />
        <StatusStripItem
          label="Ordens ativas"
          value={String(totalItems)}
          detail="Medicamentos vinculados ao atendimento"
        />
        <StatusStripItem
          label="Controlados"
          value={String(controlledItems)}
          detail="Exigem atenção na dispensação"
        />
        <StatusStripItem
          label="Modo"
          value={readOnly ? 'Leitura' : 'Edição'}
          detail={readOnly ? 'Consulta assinada ou encerrada' : 'CPOE liberado para ordens'}
        />
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Pill size={16} className="text-blue-600" />
            Ordens médicas
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Prescritor, horário, segurança e status por prescrição.
          </p>
        </div>
        {!readOnly && (
          <button
            onClick={createPrescription}
            disabled={creatingRx}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {creatingRx ? <Loader2 size={14} className="animate-spin" /> : <ClipboardPlus size={15} />}
            Nova prescrição
          </button>
        )}
      </div>

      {!readOnly && hasEditablePrescription && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Protocolos rápidos
            </span>
            {ORDER_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => applyPreset(preset)}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-700"
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {prescriptions.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-8 text-center">
          <FileText size={22} className="mx-auto text-slate-300" />
          <p className="mt-2 text-sm font-semibold text-slate-800">
            Nenhuma prescrição neste atendimento.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {readOnly ? 'O atendimento está em modo leitura.' : 'Crie a primeira prescrição para adicionar ordens.'}
          </p>
          {!readOnly && (
            <button
              onClick={createPrescription}
              disabled={creatingRx}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {creatingRx ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Criar prescrição
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {prescriptions.map((rx, index) => {
            const isComposerOpen = activePrescriptionId === rx.id && !readOnly && !rx.is_signed;
            return (
              <article key={rx.id} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                <div className="flex flex-col gap-3 border-b border-slate-100 bg-slate-50 px-3 py-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <FileText size={15} className="text-slate-400" />
                    <span className="text-sm font-semibold text-slate-900">Prescrição #{index + 1}</span>
                    <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${PRESCRIPTION_STATUS_STYLES[rx.status] ?? PRESCRIPTION_STATUS_STYLES.draft}`}>
                      {rx.status_display}
                    </span>
                    {rx.is_signed && (
                      <span className="rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700">
                        Assinada
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{formatDateTime(rx.created_at)}</span>
                    {rx.prescriber_name && <span>{rx.prescriber_name}</span>}
                    <button
                      onClick={() => printPDF(rx.id, rx.is_signed)}
                      disabled={!rx.is_signed || printingId === rx.id}
                      title={rx.is_signed ? 'Imprimir prescrição em PDF' : 'A prescrição precisa estar assinada para imprimir'}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${
                        rx.is_signed
                          ? 'bg-blue-600 text-white hover:bg-blue-700'
                          : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                      }`}
                    >
                      {printingId === rx.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Printer size={12} />
                      )}
                      Imprimir
                    </button>
                  </div>
                </div>

                {rx.items.length === 0 ? (
                  <div className="px-3 py-6 text-center text-sm text-slate-500">
                    Sem ordens nesta prescrição.
                  </div>
                ) : (
                  <div>
                    <div className="hidden border-b border-slate-100 bg-white px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 lg:grid lg:grid-cols-[minmax(220px,1.3fr)_80px_96px_minmax(220px,1fr)_140px_112px_88px]">
                      <span>Medicamento</span>
                      <span>Qtd</span>
                      <span>Unidade</span>
                      <span>Posologia</span>
                      <span>Segurança</span>
                      <span>Status</span>
                      <span className="text-right">Ação</span>
                    </div>
                    {rx.items.map(item => (
                      <OrderGridRow
                        key={item.id}
                        item={item}
                        prescriptionId={rx.id}
                        prescriptionStatus={rx.status_display}
                        readOnly={readOnly || rx.is_signed}
                        onRemove={itemId => removeItem(rx.id, itemId)}
                      />
                    ))}
                  </div>
                )}

                {isComposerOpen && (
                  <div className="border-t border-blue-100 bg-blue-50 px-3 py-3">
                    <div className="grid gap-3 lg:grid-cols-[minmax(260px,1.2fr)_90px_120px_minmax(260px,1fr)]">
                      <div className="relative">
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Medicamento
                        </label>
                        <div className="relative">
                          <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
                          <input
                            aria-label="Medicamento"
                            type="text"
                            value={selectedDrug ? selectedDrug.name : drugSearch}
                            onChange={e => {
                              setDrugSearch(e.target.value);
                              setSelectedDrug(null);
                              void searchDrugs(e.target.value);
                            }}
                            placeholder="Buscar medicamento"
                            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        {(searching || drugResults.length > 0) && !selectedDrug && drugSearch.trim() && (
                          <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
                            {searching && (
                              <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500">
                                <Loader2 size={12} className="animate-spin" />
                                Buscando...
                              </div>
                            )}
                            {drugResults.map(d => (
                              <button
                                key={d.id}
                                type="button"
                                onClick={() => {
                                  setSelectedDrug(d);
                                  setDrugSearch(d.name);
                                  setDrugResults([]);
                                }}
                                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50"
                              >
                                <span>
                                  <span className="block font-semibold text-slate-900">{d.name}</span>
                                  {d.generic_name && d.generic_name !== d.name && (
                                    <span className="block text-xs text-slate-500">{d.generic_name}</span>
                                  )}
                                </span>
                                {d.is_controlled && (
                                  <span className="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-semibold text-orange-700">
                                    Controlado
                                  </span>
                                )}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Quantidade
                        </label>
                        <input
                          aria-label="Quantidade"
                          type="number"
                          min="0.001"
                          step="0.001"
                          value={newItemForm.quantity}
                          onChange={e => setNewItemForm(f => ({ ...f, quantity: e.target.value }))}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Unidade
                        </label>
                        <input
                          aria-label="Unidade"
                          type="text"
                          value={newItemForm.unit_of_measure}
                          onChange={e => setNewItemForm(f => ({ ...f, unit_of_measure: e.target.value }))}
                          placeholder="cp, ml, ampola"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Posologia
                        </label>
                        <input
                          aria-label="Posologia"
                          type="text"
                          value={newItemForm.dosage_instructions}
                          onChange={e => setNewItemForm(f => ({ ...f, dosage_instructions: e.target.value }))}
                          placeholder="Ex.: 1 cp VO 8/8h"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3 lg:grid-cols-4">
                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Dose (valor)
                        </label>
                        <input
                          aria-label="Dose (valor)"
                          type="number"
                          min="0"
                          step="0.0001"
                          value={newItemForm.dose_amount}
                          onChange={e => setNewItemForm(f => ({ ...f, dose_amount: e.target.value }))}
                          placeholder="Ex.: 500"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Dose (unidade)
                        </label>
                        <select
                          aria-label="Dose (unidade)"
                          value={newItemForm.dose_unit}
                          onChange={e => setNewItemForm(f => ({ ...f, dose_unit: e.target.value }))}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          <option value="">—</option>
                          {DOSE_UNIT_OPTIONS.map(u => (
                            <option key={u} value={u}>{u}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Via
                        </label>
                        <select
                          aria-label="Via"
                          value={newItemForm.route}
                          onChange={e => setNewItemForm(f => ({ ...f, route: e.target.value }))}
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          <option value="">—</option>
                          {ROUTE_OPTIONS.map(r => (
                            <option key={r.value} value={r.value}>{r.label}</option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="mb-1 block text-xs font-semibold text-slate-700">
                          Doses/dia
                        </label>
                        <input
                          aria-label="Doses/dia"
                          type="number"
                          min="0"
                          step="1"
                          value={newItemForm.frequency_per_day}
                          onChange={e => setNewItemForm(f => ({ ...f, frequency_per_day: e.target.value }))}
                          placeholder="Ex.: 3"
                          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>

                    <p className="mt-2 text-xs text-slate-500">
                      Preencha para ativar a verificação de dose (injetáveis).
                    </p>

                    <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:justify-end">
                      <button
                        onClick={() => addItem(rx.id)}
                        disabled={!selectedDrug || addingItem}
                        className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
                      >
                        {addingItem ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                        Adicionar ordem
                      </button>
                      <button
                        onClick={() => { setActivePrescriptionId(null); resetComposer(); }}
                        className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-white"
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                )}

                {!readOnly && !rx.is_signed && !isComposerOpen && (
                  <div className="border-t border-slate-100 px-3 py-2.5">
                    <button
                      onClick={() => beginAddItem(rx.id)}
                      className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50"
                    >
                      <Plus size={13} />
                      Adicionar ordem
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
