"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, FlaskConical, Plus, Search, TestTube2 } from "lucide-react";
import { apiFetch } from "@/lib/api";

type LabTest = {
  id: string; code: string; name: string; specimen_type: string;
  unit: string; reference_range: string; active: boolean;
};
type LabItem = {
  id: string; test_name: string; unit: string; reference_range: string;
  result_value: string; abnormal_flag: string; abnormal_flag_display: string;
  result_notes: string; is_validated: boolean;
};
type LabOrder = {
  id: string; patient: string; patient_name: string; patient_mrn: string;
  encounter: string | null; status: string; status_display: string;
  clinical_indication: string; requested_by_name: string; requested_at: string;
  items: LabItem[];
};
type Patient = { id: string; full_name: string; medical_record_number: string };
type Paginated<T> = { results?: T[] };

function asList<T>(payload: T[] | Paginated<T>): T[] {
  return Array.isArray(payload) ? payload : (payload.results ?? []);
}

const statusStyle: Record<string, string> = {
  ordered: "bg-blue-50 text-blue-700 border-blue-200",
  collected: "bg-amber-50 text-amber-700 border-amber-200",
  in_progress: "bg-violet-50 text-violet-700 border-violet-200",
  completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  cancelled: "bg-slate-100 text-slate-500 border-slate-200",
};

export default function LaboratorioPage() {
  const [tests, setTests] = useState<LabTest[]>([]);
  const [orders, setOrders] = useState<LabOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [patientQuery, setPatientQuery] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patientId, setPatientId] = useState("");
  const [selectedTests, setSelectedTests] = useState<string[]>([]);
  const [indication, setIndication] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [editingItem, setEditingItem] = useState<string | null>(null);
  const [resultValue, setResultValue] = useState("");
  const [resultFlag, setResultFlag] = useState("normal");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, orderList] = await Promise.all([
        apiFetch<LabTest[] | Paginated<LabTest>>("/api/v1/lab-tests/?active=true"),
        apiFetch<LabOrder[] | Paginated<LabOrder>>("/api/v1/lab-orders/"),
      ]);
      setTests(asList(catalog));
      setOrders(asList(orderList));
      setError("");
    } catch {
      setError("Não foi possível carregar o laboratório.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (patientQuery.trim().length < 2) { setPatients([]); return; }
    const timer = window.setTimeout(async () => {
      try {
        const data = await apiFetch<{ results?: Patient[] } | Patient[]>(
          `/api/v1/patients/?search=${encodeURIComponent(patientQuery)}`,
        );
        setPatients(asList(data));
      } catch { setPatients([]); }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [patientQuery]);

  const counts = useMemo(() => ({
    pending: orders.filter((o) => !["completed", "cancelled"].includes(o.status)).length,
    completed: orders.filter((o) => o.status === "completed").length,
    critical: orders.flatMap((o) => o.items).filter((i) => i.abnormal_flag === "critical").length,
  }), [orders]);

  async function createOrder() {
    if (!patientId || selectedTests.length === 0) return;
    setSaving(true);
    try {
      await apiFetch("/api/v1/lab-orders/", {
        method: "POST",
        body: JSON.stringify({ patient: patientId, test_ids: selectedTests, clinical_indication: indication }),
      });
      setShowNew(false); setPatientId(""); setPatientQuery(""); setSelectedTests([]); setIndication("");
      await load();
    } catch { setError("Não foi possível criar o pedido."); }
    finally { setSaving(false); }
  }

  async function collect(orderId: string) {
    setPendingAction(`collect:${orderId}`);
    try {
      await apiFetch(`/api/v1/lab-orders/${orderId}/collect/`, { method: "POST" });
      await load();
    } catch {
      setError("Não foi possível registrar a coleta.");
    } finally {
      setPendingAction(null);
    }
  }

  async function saveResult(orderId: string, itemId: string) {
    setPendingAction(`result:${itemId}`);
    try {
      await apiFetch(`/api/v1/lab-orders/${orderId}/items/${itemId}/result/`, {
        method: "POST",
        body: JSON.stringify({ result_value: resultValue.trim(), abnormal_flag: resultFlag }),
      });
      setEditingItem(null); setResultValue(""); setResultFlag("normal");
      await load();
    } catch {
      setError("Não foi possível salvar o resultado.");
    } finally {
      setPendingAction(null);
    }
  }

  async function validateResult(orderId: string, itemId: string) {
    setPendingAction(`validate:${itemId}`);
    try {
      await apiFetch(`/api/v1/lab-orders/${orderId}/items/${itemId}/validate/`, { method: "POST" });
      await load();
    } catch {
      setError("Não foi possível validar o resultado.");
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6">
      <div className="mx-auto max-w-7xl space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2"><FlaskConical className="text-neu-brand" size={22} /><h1 className="text-2xl font-bold text-neu-ink">Laboratório</h1></div>
            <p className="mt-1 text-sm text-neu-inkSoft">Pedidos, coleta, resultados e validação clínica.</p>
          </div>
          <button type="button" aria-expanded={showNew} aria-controls="new-lab-order" onClick={() => setShowNew((v) => !v)} className="neu-btn-primary inline-flex items-center justify-center gap-2 px-4 py-2 text-sm"><Plus aria-hidden="true" size={16} />Novo pedido</button>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          {[['Pendentes', counts.pending, TestTube2], ['Concluídos', counts.completed, Check], ['Críticos', counts.critical, FlaskConical]].map(([label, value, Icon]) => {
            const MetricIcon = Icon as typeof FlaskConical;
            return <div key={label as string} className="neu-panel flex items-center gap-3 p-4"><div className="neu-icon"><MetricIcon size={18} /></div><div><p className="text-xs font-semibold uppercase tracking-wide text-neu-inkSoft">{label as string}</p><p className="text-2xl font-bold text-neu-ink">{value as number}</p></div></div>;
          })}
        </div>

        {showNew && <section id="new-lab-order" aria-labelledby="new-lab-order-title" className="neu-panel space-y-4 p-5">
          <h2 id="new-lab-order-title" className="font-semibold text-neu-ink">Novo pedido laboratorial</h2>
          <div className="relative">
            <label htmlFor="lab-patient-search" className="mb-1 block text-xs font-semibold text-neu-inkSoft">Paciente</label>
            <div className="relative"><Search aria-hidden="true" className="absolute left-3 top-2.5 text-neu-inkMuted" size={16} /><input id="lab-patient-search" role="combobox" aria-autocomplete="list" aria-expanded={patients.length > 0 && !patientId} aria-controls="lab-patient-options" autoComplete="off" value={patientQuery} onChange={(e) => { setPatientQuery(e.target.value); setPatientId(""); }} placeholder="Buscar por nome, CPF ou prontuário" className="neu-input w-full py-2 pl-9 pr-3 text-sm" /></div>
            {patients.length > 0 && !patientId && <div id="lab-patient-options" role="listbox" className="absolute z-20 mt-1 w-full rounded-lg border border-neu-app bg-neu-outer p-1 shadow-lg">{patients.slice(0, 6).map((p) => <button type="button" role="option" aria-selected="false" key={p.id} onClick={() => { setPatientId(p.id); setPatientQuery(`${p.full_name} · ${p.medical_record_number}`); setPatients([]); }} className="block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-neu-panel">{p.full_name}<span className="ml-2 font-mono text-xs text-neu-inkSoft">{p.medical_record_number}</span></button>)}</div>}
          </div>
          <div><label className="mb-2 block text-xs font-semibold text-neu-inkSoft">Exames</label><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{tests.map((test) => <label key={test.id} className="flex cursor-pointer gap-2 rounded-lg border border-neu-app bg-neu-input p-3 text-sm"><input type="checkbox" checked={selectedTests.includes(test.id)} onChange={() => setSelectedTests((current) => current.includes(test.id) ? current.filter((id) => id !== test.id) : [...current, test.id])} /><span><strong className="block text-neu-ink">{test.name}</strong><span className="text-xs text-neu-inkSoft">{test.code}{test.specimen_type ? ` · ${test.specimen_type}` : ''}</span></span></label>)}</div>{tests.length === 0 && <p className="text-sm text-neu-inkSoft">Cadastre exames no catálogo pela API/admin para iniciar.</p>}</div>
          <div><label htmlFor="lab-indication" className="mb-1 block text-xs font-semibold text-neu-inkSoft">Indicação clínica</label><textarea id="lab-indication" value={indication} onChange={(e) => setIndication(e.target.value)} className="neu-input min-h-20 w-full p-3 text-sm" /></div>
          <div className="flex justify-end gap-2"><button type="button" onClick={() => setShowNew(false)} className="neu-btn px-4 py-2 text-sm">Cancelar</button><button type="button" disabled={saving || !patientId || selectedTests.length === 0} onClick={createOrder} className="neu-btn-primary px-4 py-2 text-sm disabled:opacity-50">{saving ? 'Salvando…' : 'Criar pedido'}</button></div>
        </section>}

        {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        <section className="space-y-3">
          {loading ? <div role="status" className="neu-panel p-8 text-center text-sm text-neu-inkSoft">Carregando pedidos…</div> : orders.map((order) => <article key={order.id} className="neu-panel overflow-hidden">
            <header className="flex flex-col gap-3 border-b border-neu-app p-4 sm:flex-row sm:items-center sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold text-neu-ink">{order.patient_name}</h2><span className="font-mono text-xs text-neu-inkSoft">{order.patient_mrn}</span><span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusStyle[order.status] ?? statusStyle.cancelled}`}>{order.status_display}</span></div><p className="mt-1 text-xs text-neu-inkSoft">Solicitado por {order.requested_by_name} · {new Date(order.requested_at).toLocaleString('pt-BR')}</p></div>{order.status === 'ordered' && <button type="button" disabled={pendingAction === `collect:${order.id}`} onClick={() => collect(order.id)} className="neu-btn px-3 py-2 text-xs disabled:opacity-50">{pendingAction === `collect:${order.id}` ? "Registrando…" : "Registrar coleta"}</button>}</header>
            <div className="divide-y divide-neu-app">{order.items.map((item) => <div key={item.id} className="p-4"><div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between"><div><p className="font-medium text-neu-ink">{item.test_name}</p><p className="text-xs text-neu-inkSoft">Referência: {item.reference_range || 'não informada'} {item.unit && `· ${item.unit}`}</p>{item.result_value && <p className={`mt-1 text-sm font-bold ${item.abnormal_flag === 'critical' ? 'text-red-700' : 'text-neu-ink'}`}>{item.result_value} {item.unit}<span className="ml-2 text-xs font-semibold uppercase">{item.abnormal_flag_display}</span></p>}</div><div className="flex gap-2">{!item.is_validated && <><button onClick={() => { setEditingItem(item.id); setResultValue(item.result_value ?? ''); setResultFlag(item.abnormal_flag === 'undetermined' ? 'normal' : item.abnormal_flag); }} className="neu-btn px-3 py-2 text-xs">Lançar resultado</button>{item.result_value && <button onClick={() => validateResult(order.id, item.id)} className="neu-btn-primary px-3 py-2 text-xs">Validar</button>}</>}</div></div>{editingItem === item.id && <div className="mt-3 flex flex-col gap-2 rounded-lg bg-neu-input p-3 sm:flex-row"><input value={resultValue} onChange={(e) => setResultValue(e.target.value)} placeholder="Resultado" className="neu-input flex-1 px-3 py-2 text-sm" /><select value={resultFlag} onChange={(e) => setResultFlag(e.target.value)} className="neu-input px-3 py-2 text-sm"><option value="normal">Normal</option><option value="low">Baixo</option><option value="high">Alto</option><option value="critical">Crítico</option><option value="undetermined">Indeterminado</option></select><button disabled={!resultValue} onClick={() => saveResult(order.id, item.id)} className="neu-btn-primary px-4 py-2 text-sm disabled:opacity-50">Salvar</button></div>}</div>)}</div>
          </article>)}
          {!loading && !error && orders.length === 0 && <div className="neu-panel p-10 text-center"><FlaskConical aria-hidden="true" className="mx-auto text-neu-inkMuted" size={30} /><p className="mt-3 font-medium text-neu-ink">Nenhum pedido laboratorial</p><p className="text-sm text-neu-inkSoft">Crie o primeiro pedido para iniciar o fluxo.</p></div>}
        </section>
      </div>
    </main>
  );
}
