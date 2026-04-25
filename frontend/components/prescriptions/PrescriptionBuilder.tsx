'use client';

import { useState, useEffect, useCallback } from 'react';
import { Loader2, Plus, Printer, FileText, Pill } from 'lucide-react';
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
    throw new Error(data.error ?? `Erro ${res.status}`);
  }
  return res.json();
}

function ItemRow({
  item,
  prescriptionId,
  readOnly,
  onRemove,
}: {
  item: PrescriptionItem;
  prescriptionId: string;
  readOnly: boolean;
  onRemove: (id: string) => void;
}) {
  const [alertsToShow, setAlertsToShow] = useState<SafetyAlert[] | null>(null);

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-slate-100 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-slate-800">{item.drug_name}</span>
          {item.drug_is_controlled && (
            <span className="text-xs px-1.5 py-0.5 bg-orange-50 text-orange-700 border border-orange-200 rounded font-medium">
              Controlado
            </span>
          )}
          <SafetyBadge
            prescriptionId={prescriptionId}
            itemId={item.id}
            onAlertsClick={alerts => setAlertsToShow(alerts)}
          />
        </div>
        <p className="text-xs text-slate-500 mt-0.5">
          {item.drug_generic_name && item.drug_generic_name !== item.drug_name
            ? `${item.drug_generic_name} · `
            : ''}
          {item.quantity} {item.unit_of_measure}
          {item.dosage_instructions ? ` · ${item.dosage_instructions}` : ''}
        </p>
      </div>
      {!readOnly && (
        <button
          onClick={() => onRemove(item.id)}
          className="text-xs text-red-500 hover:text-red-700 shrink-0 mt-0.5"
          aria-label="Remover item"
        >
          Remover
        </button>
      )}

      {alertsToShow && (
        <SafetyAlertModal
          alerts={alertsToShow}
          onClose={() => setAlertsToShow(null)}
        />
      )}
    </div>
  );
}

export function PrescriptionBuilder({ encounterId, readOnly = false }: PrescriptionBuilderProps) {
  const [prescriptions, setPrescriptions] = useState<Prescription[]>([]);
  const [loading, setLoading] = useState(true);
  const [creatingRx, setCreatingRx] = useState(false);
  const [printingId, setPrintingId] = useState<string | null>(null);
  const [drugSearch, setDrugSearch] = useState('');
  const [drugResults, setDrugResults] = useState<Drug[]>([]);
  const [searching, setSearching] = useState(false);
  const [activePrescriptionId, setActivePrescriptionId] = useState<string | null>(null);
  const [addingItem, setAddingItem] = useState(false);
  const [newItemForm, setNewItemForm] = useState({
    quantity: '1',
    unit_of_measure: 'cp',
    dosage_instructions: '',
  });
  const [selectedDrug, setSelectedDrug] = useState<Drug | null>(null);

  const loadPrescriptions = useCallback(async () => {
    try {
      const data = await apiFetch<{ results?: Prescription[] } | Prescription[]>(
        `/prescriptions/?encounter=${encounterId}`
      );
      const list = Array.isArray(data) ? data : (data as any).results ?? [];
      setPrescriptions(list);
    } catch {
      // fail-open: show empty state
    } finally {
      setLoading(false);
    }
  }, [encounterId]);

  useEffect(() => { loadPrescriptions(); }, [loadPrescriptions]);

  const createPrescription = async () => {
    setCreatingRx(true);
    try {
      const rx = await apiFetch<Prescription>('/prescriptions/', {
        method: 'POST',
        body: JSON.stringify({ encounter: encounterId }),
      });
      setPrescriptions(prev => [...prev, { ...rx, items: [] }]);
      setActivePrescriptionId(rx.id);
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro ao criar receita.');
    } finally {
      setCreatingRx(false);
    }
  };

  const searchDrugs = async (q: string) => {
    if (!q.trim()) { setDrugResults([]); return; }
    setSearching(true);
    try {
      const data = await apiFetch<{ results?: Drug[] } | Drug[]>(`/pharmacy/drugs/?search=${encodeURIComponent(q)}&limit=5`);
      const list = Array.isArray(data) ? data : (data as any).results ?? [];
      setDrugResults(list);
    } catch {
      setDrugResults([]);
    } finally {
      setSearching(false);
    }
  };

  const addItem = async (prescriptionId: string) => {
    if (!selectedDrug) return;
    setAddingItem(true);
    try {
      const item = await apiFetch<PrescriptionItem>('/prescription-items/', {
        method: 'POST',
        body: JSON.stringify({
          prescription: prescriptionId,
          drug: selectedDrug.id,
          quantity: parseFloat(newItemForm.quantity) || 1,
          unit_of_measure: newItemForm.unit_of_measure,
          dosage_instructions: newItemForm.dosage_instructions,
        }),
      });
      setPrescriptions(prev =>
        prev.map(rx => rx.id === prescriptionId ? { ...rx, items: [...rx.items, item] } : rx)
      );
      setSelectedDrug(null);
      setDrugSearch('');
      setDrugResults([]);
      setNewItemForm({ quantity: '1', unit_of_measure: 'cp', dosage_instructions: '' });
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro ao adicionar item.');
    } finally {
      setAddingItem(false);
    }
  };

  const removeItem = async (prescriptionId: string, itemId: string) => {
    try {
      await apiFetch(`/prescription-items/${itemId}/`, { method: 'DELETE' });
      setPrescriptions(prev =>
        prev.map(rx => rx.id === prescriptionId
          ? { ...rx, items: rx.items.filter(i => i.id !== itemId) }
          : rx
        )
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Erro ao remover item.');
    }
  };

  const printPDF = async (prescriptionId: string, isSigned: boolean) => {
    if (!isSigned) {
      alert('A receita precisa estar assinada para imprimir. Assine a consulta primeiro.');
      return;
    }
    setPrintingId(prescriptionId);
    try {
      const token = getAccessToken();
      const res = await fetch(`/api/v1/prescriptions/${prescriptionId}/pdf/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch {
      alert('Erro ao gerar PDF. Verifique se a receita está assinada.');
    } finally {
      setPrintingId(null);
    }
  };

  if (loading) {
    return (
      <div className="py-4 flex justify-center">
        <Loader2 className="animate-spin text-slate-300" size={20} />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-1.5">
          <Pill size={15} /> Receitas
        </h3>
        {!readOnly && (
          <button
            onClick={createPrescription}
            disabled={creatingRx}
            className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 font-medium disabled:opacity-40"
          >
            {creatingRx ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
            Nova Receita
          </button>
        )}
      </div>

      {prescriptions.length === 0 ? (
        <p className="text-xs text-slate-400 text-center py-4">
          {readOnly ? 'Nenhuma receita nesta consulta.' : 'Nenhuma receita criada ainda.'}
        </p>
      ) : (
        prescriptions.map(rx => (
          <div key={rx.id} className="border border-slate-200 rounded-lg overflow-hidden">
            {/* Prescription header */}
            <div className="px-3 py-2.5 bg-slate-50 flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <FileText size={14} className="text-slate-400" />
                <span className="text-xs font-medium text-slate-700">{rx.status_display}</span>
                {rx.is_signed && (
                  <span className="text-xs text-green-600 font-medium">✓ Assinada</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* Imprimir Receita button */}
                <button
                  onClick={() => printPDF(rx.id, rx.is_signed)}
                  disabled={!rx.is_signed || printingId === rx.id}
                  title={rx.is_signed ? 'Imprimir Receita (PDF)' : 'A receita precisa estar assinada para imprimir'}
                  className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg transition ${
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
                  Imprimir Receita
                </button>
              </div>
            </div>

            {/* Items */}
            <div className="px-3">
              {rx.items.length === 0 ? (
                <p className="text-xs text-slate-400 py-3 text-center">
                  {readOnly ? 'Sem itens.' : 'Adicione medicamentos abaixo.'}
                </p>
              ) : (
                rx.items.map(item => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    prescriptionId={rx.id}
                    readOnly={readOnly}
                    onRemove={itemId => removeItem(rx.id, itemId)}
                  />
                ))
              )}
            </div>

            {/* Add item form */}
            {!readOnly && activePrescriptionId === rx.id && (
              <div className="px-3 pb-3 pt-2 border-t border-slate-100 space-y-2">
                {/* Drug search */}
                <div className="relative">
                  <input
                    type="text"
                    value={selectedDrug ? selectedDrug.name : drugSearch}
                    onChange={e => {
                      setDrugSearch(e.target.value);
                      setSelectedDrug(null);
                      searchDrugs(e.target.value);
                    }}
                    placeholder="Buscar medicamento..."
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  {drugResults.length > 0 && !selectedDrug && (
                    <div className="absolute z-10 w-full bg-white border border-slate-200 rounded-lg shadow-lg mt-1 max-h-40 overflow-y-auto">
                      {searching && <div className="px-3 py-2 text-xs text-slate-400">Buscando...</div>}
                      {drugResults.map(d => (
                        <button
                          key={d.id}
                          onClick={() => {
                            setSelectedDrug(d);
                            setDrugSearch(d.name);
                            setDrugResults([]);
                          }}
                          className="w-full text-left px-3 py-2 text-xs hover:bg-slate-50 flex items-center justify-between"
                        >
                          <span className="font-medium">{d.name}</span>
                          {d.is_controlled && (
                            <span className="text-orange-600 text-xs">Controlado</span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {selectedDrug && (
                  <div className="grid grid-cols-3 gap-2">
                    <input
                      type="number"
                      min="0.001"
                      step="0.001"
                      value={newItemForm.quantity}
                      onChange={e => setNewItemForm(f => ({ ...f, quantity: e.target.value }))}
                      placeholder="Qtd"
                      className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      type="text"
                      value={newItemForm.unit_of_measure}
                      onChange={e => setNewItemForm(f => ({ ...f, unit_of_measure: e.target.value }))}
                      placeholder="Un (cp, ml...)"
                      className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      type="text"
                      value={newItemForm.dosage_instructions}
                      onChange={e => setNewItemForm(f => ({ ...f, dosage_instructions: e.target.value }))}
                      placeholder="Posologia"
                      className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={() => addItem(rx.id)}
                    disabled={!selectedDrug || addingItem}
                    className="flex-1 bg-blue-600 text-white text-xs font-medium py-1.5 rounded-lg hover:bg-blue-700 disabled:opacity-40 transition flex items-center justify-center gap-1"
                  >
                    {addingItem ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
                    Adicionar
                  </button>
                  <button
                    onClick={() => { setActivePrescriptionId(null); setSelectedDrug(null); setDrugSearch(''); setDrugResults([]); }}
                    className="text-xs text-slate-500 hover:text-slate-700 px-3"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}

            {!readOnly && activePrescriptionId !== rx.id && !rx.is_signed && (
              <div className="px-3 pb-2.5">
                <button
                  onClick={() => setActivePrescriptionId(rx.id)}
                  className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
                >
                  <Plus size={12} /> Adicionar medicamento
                </button>
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
