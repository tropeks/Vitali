"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, FlaskConical, Plus, Search, TestTube2, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { ImagingPanel } from "@/components/imaging/ImagingPanel";

type LabTest = {
  id: string;
  code: string;
  name: string;
  specimen_type: string;
  unit: string;
  reference_range: string;
  active: boolean;
  category?: string;
  category_display?: string;
  result_type?: string;
  result_type_display?: string;
  method?: string;
  loinc_code?: string;
  components?: Array<{
    code?: string;
    name: string;
    unit?: string;
    reference_range?: string;
  }>;
};
type LabItem = {
  id: string;
  test_name: string;
  unit: string;
  reference_range: string;
  result_value: string;
  abnormal_flag: string;
  abnormal_flag_display: string;
  result_notes: string;
  is_validated: boolean;
  category?: string;
  category_display?: string;
  result_type?: string;
  result_type_display?: string;
  method?: string;
  specimen_type?: string;
  components?: Array<{
    code?: string;
    name: string;
    unit?: string;
    value?: string;
  }>;
  result_data?: Record<string, unknown>;
  microbiology?: Record<string, unknown>;
};
type LabOrder = {
  id: string;
  patient: string;
  patient_name: string;
  patient_mrn: string;
  encounter: string | null;
  status: string;
  status_display: string;
  clinical_indication: string;
  requested_by_name: string;
  requested_at: string;
  items: LabItem[];
  accession_number?: string;
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

const categoryLabels: Record<string, string> = {
  hematology: "Hematologia",
  biochemistry: "Bioquímica",
  immunology: "Imunologia e sorologia",
  hormones: "Hormônios",
  microbiology: "Microbiologia",
  urinalysis: "Urinálise",
  parasitology: "Parasitologia",
  coagulation: "Coagulação",
  toxicology: "Toxicologia",
  molecular: "Genética e molecular",
  pathology: "Anatomia patológica",
  rapid_test: "Testes rápidos",
  other: "Outros",
};

const resultTypeLabels: Record<string, string> = {
  numeric: "Numérico",
  qualitative: "Qualitativo",
  text: "Texto",
  panel: "Painel",
  microbiology: "Microbiologia",
};

type ResultEditorProps = {
  item: LabItem;
  resultValue: string;
  setResultValue: (value: string) => void;
  resultFlag: string;
  setResultFlag: (value: string) => void;
  resultNotes: string;
  setResultNotes: (value: string) => void;
  componentValues: Record<string, string>;
  setComponentValues: (value: Record<string, string>) => void;
  organism: string;
  setOrganism: (value: string) => void;
  antibiogram: string;
  setAntibiogram: (value: string) => void;
  saving: boolean;
  onSave: () => void;
};

function ResultEditor(props: ResultEditorProps) {
  const { item } = props;
  const type = item.result_type || "text";
  const components = item.components ?? [];
  const hasResult =
    props.resultValue.trim() ||
    Object.values(props.componentValues).some((value) => value.trim()) ||
    props.organism.trim();
  return (
    <div
      className="mt-3 space-y-3 rounded-lg bg-neu-input p-3"
      aria-label={`Resultado de ${item.test_name}`}
    >
      {type === "panel" && components.length > 0 ? (
        <fieldset className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <legend className="sr-only">Componentes do painel</legend>
          {components.map((component, index) => {
            const key = component.code || component.name || String(index);
            return (
              <label
                key={key}
                className="text-xs font-semibold text-neu-inkSoft"
              >
                {component.name}
                <span className="mt-1 flex items-center gap-2">
                  <input
                    value={props.componentValues[key] ?? ""}
                    onChange={(e) =>
                      props.setComponentValues({
                        ...props.componentValues,
                        [key]: e.target.value,
                      })
                    }
                    inputMode="decimal"
                    className="neu-input min-w-0 flex-1 px-3 py-2 text-sm font-normal"
                  />
                  <span>{component.unit}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
      ) : type === "qualitative" ? (
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Resultado
          <select
            value={props.resultValue}
            onChange={(e) => props.setResultValue(e.target.value)}
            className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
          >
            <option value="">Selecione</option>
            <option>Positivo</option>
            <option>Negativo</option>
            <option>Reagente</option>
            <option>Não reagente</option>
            <option>Indeterminado</option>
          </select>
        </label>
      ) : (
        type !== "microbiology" && (
          <label className="block text-xs font-semibold text-neu-inkSoft">
            Resultado
            {type === "text" ? (
              <textarea
                value={props.resultValue}
                onChange={(e) => props.setResultValue(e.target.value)}
                className="neu-input mt-1 min-h-20 w-full p-3 text-sm font-normal"
              />
            ) : (
              <input
                value={props.resultValue}
                onChange={(e) => props.setResultValue(e.target.value)}
                inputMode={type === "numeric" ? "decimal" : "text"}
                className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
              />
            )}
          </label>
        )
      )}
      {type === "microbiology" && (
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="sr-only">Microbiologia</legend>
          <label className="text-xs font-semibold text-neu-inkSoft">
            Microrganismo isolado
            <input
              value={props.organism}
              onChange={(e) => props.setOrganism(e.target.value)}
              className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
            />
          </label>
          <label className="text-xs font-semibold text-neu-inkSoft">
            Antibiograma{" "}
            <span className="font-normal">(um antimicrobiano por linha)</span>
            <textarea
              value={props.antibiogram}
              onChange={(e) => props.setAntibiogram(e.target.value)}
              placeholder="Amoxicilina — S\nCiprofloxacino — R"
              className="neu-input mt-1 min-h-24 w-full p-3 text-sm font-normal"
            />
          </label>
        </fieldset>
      )}
      <div className="grid gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
        <label className="text-xs font-semibold text-neu-inkSoft">
          Interpretação
          <select
            value={props.resultFlag}
            onChange={(e) => props.setResultFlag(e.target.value)}
            className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
          >
            <option value="normal">Normal</option>
            <option value="low">Baixo</option>
            <option value="high">Alto</option>
            <option value="critical">Crítico</option>
            <option value="undetermined">Indeterminado</option>
          </select>
        </label>
        <label className="text-xs font-semibold text-neu-inkSoft">
          Observações
          <input
            value={props.resultNotes}
            onChange={(e) => props.setResultNotes(e.target.value)}
            className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
          />
        </label>
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          disabled={!hasResult || props.saving}
          onClick={props.onSave}
          className="neu-btn-primary px-4 py-2 text-sm disabled:opacity-50"
        >
          {props.saving ? "Salvando…" : "Salvar resultado"}
        </button>
      </div>
    </div>
  );
}

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
  const [resultNotes, setResultNotes] = useState("");
  const [componentValues, setComponentValues] = useState<
    Record<string, string>
  >({});
  const [organism, setOrganism] = useState("");
  const [antibiogram, setAntibiogram] = useState("");
  const [collectingOrder, setCollectingOrder] = useState<string | null>(null);
  const [accessionNumber, setAccessionNumber] = useState("");
  const [specimenIdentifier, setSpecimenIdentifier] = useState("");
  const [specimenType, setSpecimenType] = useState("");
  const [specimenContainer, setSpecimenContainer] = useState("");
  const [collectionNotes, setCollectionNotes] = useState("");
  const [signingOrder, setSigningOrder] = useState<string | null>(null);
  const [certificateFile, setCertificateFile] = useState<File | null>(null);
  const [certificatePassword, setCertificatePassword] = useState("");
  const [releasedOrders, setReleasedOrders] = useState<string[]>([]);
  const [orderQuery, setOrderQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, orderList] = await Promise.all([
        apiFetch<LabTest[] | Paginated<LabTest>>(
          "/api/v1/lab-tests/?active=true",
        ),
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

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (patientQuery.trim().length < 2) {
      setPatients([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const data = await apiFetch<{ results?: Patient[] } | Patient[]>(
          `/api/v1/patients/?search=${encodeURIComponent(patientQuery)}`,
        );
        setPatients(asList(data));
      } catch {
        setPatients([]);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [patientQuery]);

  const counts = useMemo(
    () => ({
      pending: orders.filter(
        (o) => !["completed", "cancelled"].includes(o.status),
      ).length,
      completed: orders.filter((o) => o.status === "completed").length,
      critical: orders
        .flatMap((o) => o.items)
        .filter((i) => i.abnormal_flag === "critical").length,
    }),
    [orders],
  );

  const categories = useMemo(
    () => Array.from(new Set(tests.map((test) => test.category || "other"))),
    [tests],
  );
  const groupedTests = useMemo(
    () =>
      tests
        .filter(
          (test) =>
            categoryFilter === "all" ||
            (test.category || "other") === categoryFilter,
        )
        .reduce<Record<string, LabTest[]>>((groups, test) => {
          const category = test.category || "other";
          (groups[category] ??= []).push(test);
          return groups;
        }, {}),
    [tests, categoryFilter],
  );
  const filteredOrders = useMemo(() => {
    const query = orderQuery.trim().toLocaleLowerCase("pt-BR");
    return orders.filter(
      (order) =>
        (statusFilter === "all" || order.status === statusFilter) &&
        (!query ||
          [order.patient_name, order.patient_mrn, order.accession_number].some(
            (value) => value?.toLocaleLowerCase("pt-BR").includes(query),
          )),
    );
  }, [orders, orderQuery, statusFilter]);

  async function createOrder() {
    if (!patientId || selectedTests.length === 0) return;
    setSaving(true);
    try {
      await apiFetch("/api/v1/lab-orders/", {
        method: "POST",
        body: JSON.stringify({
          patient: patientId,
          test_ids: selectedTests,
          clinical_indication: indication,
        }),
      });
      setShowNew(false);
      setPatientId("");
      setPatientQuery("");
      setSelectedTests([]);
      setIndication("");
      await load();
    } catch {
      setError("Não foi possível criar o pedido.");
    } finally {
      setSaving(false);
    }
  }

  async function collect(orderId: string) {
    setPendingAction(`collect:${orderId}`);
    try {
      await apiFetch(`/api/v1/lab-orders/${orderId}/collect/`, {
        method: "POST",
        body: JSON.stringify({
          accession_number: accessionNumber.trim(),
          collection_notes: collectionNotes.trim(),
          specimen_details:
            specimenType.trim() ||
            specimenIdentifier.trim() ||
            specimenContainer.trim()
              ? [
                  {
                    identifier: specimenIdentifier.trim(),
                    type: specimenType.trim(),
                    container: specimenContainer.trim(),
                  },
                ]
              : [],
        }),
      });
      setCollectingOrder(null);
      setAccessionNumber("");
      setSpecimenIdentifier("");
      setSpecimenType("");
      setSpecimenContainer("");
      setCollectionNotes("");
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
        body: JSON.stringify({
          result_value:
            resultValue.trim() || Object.values(componentValues).join("; "),
          abnormal_flag: resultFlag,
          result_notes: resultNotes.trim(),
          ...(Object.keys(componentValues).length
            ? { result_data: { components: componentValues } }
            : {}),
          ...(organism.trim() || antibiogram.trim()
            ? {
                microbiology: {
                  organisms: organism.trim()
                    ? [
                        {
                          name: organism.trim(),
                          antibiogram: antibiogram
                            .split("\n")
                            .map((line) => {
                              const [antimicrobial, interpretation = ""] =
                                line.split(/\s*[—–-]\s*/);
                              return {
                                antimicrobial: antimicrobial.trim(),
                                interpretation: interpretation.trim(),
                              };
                            })
                            .filter(
                              (entry) =>
                                entry.antimicrobial && entry.interpretation,
                            ),
                        },
                      ]
                    : [],
                },
              }
            : {}),
        }),
      });
      setEditingItem(null);
      setResultValue("");
      setResultFlag("normal");
      setResultNotes("");
      setComponentValues({});
      setOrganism("");
      setAntibiogram("");
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
      await apiFetch(
        `/api/v1/lab-orders/${orderId}/items/${itemId}/validate/`,
        { method: "POST" },
      );
      await load();
    } catch {
      setError("Não foi possível validar o resultado.");
    } finally {
      setPendingAction(null);
    }
  }

  async function signReport(orderId: string) {
    if (!certificateFile) return;
    setPendingAction(`sign:${orderId}`);
    try {
      const bytes = new Uint8Array(await certificateFile.arrayBuffer());
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      await apiFetch(`/api/v1/lab-orders/${orderId}/report/sign/`, {
        method: "POST",
        body: JSON.stringify({
          pkcs12_b64: window.btoa(binary),
          pkcs12_password: certificatePassword,
        }),
      });
      setReleasedOrders((current) => [...current, orderId]);
      setSigningOrder(null);
      setCertificateFile(null);
      setCertificatePassword("");
    } catch {
      setError("Não foi possível assinar e liberar o laudo.");
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <main className="flex-1 overflow-y-auto p-4 lg:p-6">
      <div className="mx-auto max-w-7xl space-y-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <FlaskConical className="text-neu-brand" size={22} />
              <h1 className="text-2xl font-bold text-neu-ink">Laboratório</h1>
            </div>
            <p className="mt-1 text-sm text-neu-inkSoft">
              Pedidos, coleta, resultados e validação clínica.
            </p>
          </div>
          <button
            type="button"
            aria-expanded={showNew}
            aria-controls="new-lab-order"
            onClick={() => setShowNew((v) => !v)}
            className="neu-btn-primary inline-flex items-center justify-center gap-2 px-4 py-2 text-sm"
          >
            <Plus aria-hidden="true" size={16} />
            Novo pedido
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ["Pendentes", counts.pending, TestTube2],
            ["Concluídos", counts.completed, Check],
            ["Críticos", counts.critical, FlaskConical],
          ].map(([label, value, Icon]) => {
            const MetricIcon = Icon as typeof FlaskConical;
            return (
              <div
                key={label as string}
                className="neu-panel flex items-center gap-3 p-4"
              >
                <div className="neu-icon">
                  <MetricIcon size={18} />
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-neu-inkSoft">
                    {label as string}
                  </p>
                  <p className="text-2xl font-bold text-neu-ink">
                    {value as number}
                  </p>
                </div>
              </div>
            );
          })}
        </div>

        {showNew && (
          <section
            id="new-lab-order"
            aria-labelledby="new-lab-order-title"
            className="neu-panel space-y-4 p-5"
          >
            <h2 id="new-lab-order-title" className="font-semibold text-neu-ink">
              Novo pedido laboratorial
            </h2>
            <div className="relative">
              <label
                htmlFor="lab-patient-search"
                className="mb-1 block text-xs font-semibold text-neu-inkSoft"
              >
                Paciente
              </label>
              <div className="relative">
                <Search
                  aria-hidden="true"
                  className="absolute left-3 top-2.5 text-neu-inkMuted"
                  size={16}
                />
                <input
                  id="lab-patient-search"
                  role="combobox"
                  aria-autocomplete="list"
                  aria-expanded={patients.length > 0 && !patientId}
                  aria-controls="lab-patient-options"
                  autoComplete="off"
                  value={patientQuery}
                  onChange={(e) => {
                    setPatientQuery(e.target.value);
                    setPatientId("");
                  }}
                  placeholder="Buscar por nome, CPF ou prontuário"
                  className="neu-input w-full py-2 pl-9 pr-3 text-sm"
                />
              </div>
              {patients.length > 0 && !patientId && (
                <div
                  id="lab-patient-options"
                  role="listbox"
                  className="absolute z-20 mt-1 w-full rounded-lg border border-neu-app bg-neu-outer p-1 shadow-lg"
                >
                  {patients.slice(0, 6).map((p) => (
                    <button
                      type="button"
                      role="option"
                      aria-selected="false"
                      key={p.id}
                      onClick={() => {
                        setPatientId(p.id);
                        setPatientQuery(
                          `${p.full_name} · ${p.medical_record_number}`,
                        );
                        setPatients([]);
                      }}
                      className="block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-neu-panel"
                    >
                      {p.full_name}
                      <span className="ml-2 font-mono text-xs text-neu-inkSoft">
                        {p.medical_record_number}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                <label className="block text-xs font-semibold text-neu-inkSoft">
                  Exames
                </label>
                <select
                  aria-label="Filtrar catálogo por categoria"
                  value={categoryFilter}
                  onChange={(e) => setCategoryFilter(e.target.value)}
                  className="neu-input px-3 py-2 text-sm"
                >
                  <option value="all">Todas as categorias</option>
                  {categories.map((category) => (
                    <option key={category} value={category}>
                      {categoryLabels[category] || category}
                    </option>
                  ))}
                </select>
              </div>
              <div className="max-h-[28rem] space-y-4 overflow-y-auto pr-1">
                {Object.entries(groupedTests).map(
                  ([category, categoryTests]) => (
                    <fieldset key={category}>
                      <legend className="mb-2 text-sm font-semibold text-neu-ink">
                        {categoryLabels[category] || category}
                      </legend>
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {categoryTests.map((test) => (
                          <label
                            key={test.id}
                            className="flex cursor-pointer gap-2 rounded-lg border border-neu-app bg-neu-input p-3 text-sm focus-within:ring-2 focus-within:ring-neu-brand"
                          >
                            <input
                              type="checkbox"
                              checked={selectedTests.includes(test.id)}
                              onChange={() =>
                                setSelectedTests((current) =>
                                  current.includes(test.id)
                                    ? current.filter((id) => id !== test.id)
                                    : [...current, test.id],
                                )
                              }
                            />
                            <span>
                              <strong className="block text-neu-ink">
                                {test.name}
                              </strong>
                              <span className="text-xs text-neu-inkSoft">
                                {[
                                  test.code,
                                  test.specimen_type,
                                  test.method,
                                  resultTypeLabels[test.result_type || ""],
                                ]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ),
                )}
              </div>
              {tests.length === 0 && (
                <p className="text-sm text-neu-inkSoft">
                  Cadastre exames no catálogo pela API/admin para iniciar.
                </p>
              )}
            </div>
            <div>
              <label
                htmlFor="lab-indication"
                className="mb-1 block text-xs font-semibold text-neu-inkSoft"
              >
                Indicação clínica
              </label>
              <textarea
                id="lab-indication"
                value={indication}
                onChange={(e) => setIndication(e.target.value)}
                className="neu-input min-h-20 w-full p-3 text-sm"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowNew(false)}
                className="neu-btn px-4 py-2 text-sm"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={saving || !patientId || selectedTests.length === 0}
                onClick={createOrder}
                className="neu-btn-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                {saving ? "Salvando…" : "Criar pedido"}
              </button>
            </div>
          </section>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}
        <section
          aria-label="Filtros dos pedidos"
          className="neu-panel grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_13rem]"
        >
          <label className="relative">
            <span className="sr-only">Buscar pedidos</span>
            <Search
              aria-hidden="true"
              className="absolute left-3 top-2.5 text-neu-inkMuted"
              size={16}
            />
            <input
              value={orderQuery}
              onChange={(e) => setOrderQuery(e.target.value)}
              placeholder="Paciente, prontuário ou acesso"
              className="neu-input w-full py-2 pl-9 pr-9 text-sm"
            />
            {orderQuery && (
              <button
                type="button"
                aria-label="Limpar busca"
                onClick={() => setOrderQuery("")}
                className="absolute right-2 top-2 p-1 text-neu-inkSoft"
              >
                <X size={15} />
              </button>
            )}
          </label>
          <label>
            <span className="sr-only">Filtrar por status</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="neu-input w-full px-3 py-2 text-sm"
            >
              <option value="all">Todos os status</option>
              <option value="ordered">Solicitado</option>
              <option value="collected">Coletado</option>
              <option value="in_progress">Em análise</option>
              <option value="completed">Concluído</option>
              <option value="cancelled">Cancelado</option>
            </select>
          </label>
        </section>
        <section className="space-y-3">
          {loading ? (
            <div
              role="status"
              className="neu-panel p-8 text-center text-sm text-neu-inkSoft"
            >
              Carregando pedidos…
            </div>
          ) : (
            filteredOrders.map((order) => (
              <article key={order.id} className="neu-panel overflow-hidden">
                <header className="flex flex-col gap-3 border-b border-neu-app p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold text-neu-ink">
                        {order.patient_name}
                      </h2>
                      <span className="font-mono text-xs text-neu-inkSoft">
                        {order.patient_mrn}
                      </span>
                      {order.accession_number && (
                        <span className="font-mono text-xs text-neu-inkSoft">
                          Acesso {order.accession_number}
                        </span>
                      )}
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${statusStyle[order.status] ?? statusStyle.cancelled}`}
                      >
                        {order.status_display}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-neu-inkSoft">
                      Solicitado por {order.requested_by_name} ·{" "}
                      {new Date(order.requested_at).toLocaleString("pt-BR")}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {order.status === "ordered" && (
                      <button
                        type="button"
                        disabled={pendingAction === `collect:${order.id}`}
                        onClick={() => setCollectingOrder(order.id)}
                        className="neu-btn px-3 py-2 text-xs disabled:opacity-50"
                      >
                        {pendingAction === `collect:${order.id}`
                          ? "Registrando…"
                          : "Registrar coleta"}
                      </button>
                    )}
                    {order.status === "completed" &&
                      !releasedOrders.includes(order.id) && (
                        <button
                          type="button"
                          onClick={() => setSigningOrder(order.id)}
                          className="neu-btn-primary px-3 py-2 text-xs"
                        >
                          Assinar e liberar laudo
                        </button>
                      )}
                    {releasedOrders.includes(order.id) && (
                      <span className="rounded-full bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">
                        Laudo liberado
                      </span>
                    )}
                  </div>
                </header>
                {signingOrder === order.id && (
                  <div className="grid gap-3 border-b border-neu-app bg-neu-input p-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                    <label className="text-xs font-semibold text-neu-inkSoft">
                      Certificado ICP-Brasil A1 (.pfx/.p12)
                      <input
                        type="file"
                        accept=".pfx,.p12,application/x-pkcs12"
                        onChange={(e) =>
                          setCertificateFile(e.target.files?.[0] ?? null)
                        }
                        className="mt-1 block w-full text-sm font-normal"
                      />
                    </label>
                    <label className="text-xs font-semibold text-neu-inkSoft">
                      Senha do certificado
                      <input
                        type="password"
                        value={certificatePassword}
                        onChange={(e) => setCertificatePassword(e.target.value)}
                        className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <div className="flex items-end justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setSigningOrder(null)}
                        className="neu-btn px-3 py-2 text-xs"
                      >
                        Cancelar
                      </button>
                      <button
                        type="button"
                        disabled={
                          !certificateFile ||
                          pendingAction === `sign:${order.id}`
                        }
                        onClick={() => signReport(order.id)}
                        className="neu-btn-primary px-3 py-2 text-xs disabled:opacity-50"
                      >
                        {pendingAction === `sign:${order.id}`
                          ? "Assinando…"
                          : "Confirmar assinatura"}
                      </button>
                    </div>
                    <p className="text-xs text-neu-inkSoft sm:col-span-3">
                      O certificado é enviado apenas para esta assinatura e não
                      é armazenado.
                    </p>
                  </div>
                )}
                {collectingOrder === order.id && (
                  <div className="grid gap-3 border-b border-neu-app bg-neu-input p-4 sm:grid-cols-2 lg:grid-cols-4">
                    <label className="text-xs font-semibold text-neu-inkSoft">
                      Número de acesso
                      <input
                        value={accessionNumber}
                        onChange={(e) => setAccessionNumber(e.target.value)}
                        className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <label className="text-xs font-semibold text-neu-inkSoft">
                      Identificador da amostra
                      <input
                        value={specimenIdentifier}
                        onChange={(e) => setSpecimenIdentifier(e.target.value)}
                        className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <label className="text-xs font-semibold text-neu-inkSoft">
                      Material biológico
                      <input
                        value={specimenType}
                        onChange={(e) => setSpecimenType(e.target.value)}
                        placeholder="Sangue, urina…"
                        className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <label className="text-xs font-semibold text-neu-inkSoft">
                      Recipiente
                      <input
                        value={specimenContainer}
                        onChange={(e) => setSpecimenContainer(e.target.value)}
                        placeholder="Tubo EDTA…"
                        className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <label className="text-xs font-semibold text-neu-inkSoft sm:col-span-2 lg:col-span-3">
                      Observações da coleta
                      <input
                        value={collectionNotes}
                        onChange={(e) => setCollectionNotes(e.target.value)}
                        className="neu-input mt-1 w-full px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <div className="flex items-end justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setCollectingOrder(null)}
                        className="neu-btn px-3 py-2 text-xs"
                      >
                        Cancelar
                      </button>
                      <button
                        type="button"
                        disabled={pendingAction === `collect:${order.id}`}
                        onClick={() => collect(order.id)}
                        className="neu-btn-primary px-3 py-2 text-xs disabled:opacity-50"
                      >
                        Confirmar coleta
                      </button>
                    </div>
                  </div>
                )}
                <div className="divide-y divide-neu-app">
                  {order.items.map((item) => (
                    <div key={item.id} className="p-4">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="font-medium text-neu-ink">
                              {item.test_name}
                            </p>
                            {item.category && (
                              <span className="rounded bg-neu-input px-2 py-0.5 text-xs text-neu-inkSoft">
                                {item.category_display ||
                                  categoryLabels[item.category] ||
                                  item.category}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-neu-inkSoft">
                            {[
                              item.specimen_type,
                              item.method,
                              item.result_type_display ||
                                resultTypeLabels[item.result_type || ""],
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                          <p className="text-xs text-neu-inkSoft">
                            Referência:{" "}
                            {item.reference_range || "não informada"}{" "}
                            {item.unit && `· ${item.unit}`}
                          </p>
                          {item.result_value && (
                            <p
                              className={`mt-1 text-sm font-bold ${item.abnormal_flag === "critical" ? "text-red-700" : "text-neu-ink"}`}
                            >
                              {item.result_value} {item.unit}
                              <span className="ml-2 text-xs font-semibold uppercase">
                                {item.abnormal_flag_display}
                              </span>
                            </p>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {!item.is_validated && (
                            <>
                              <button
                                onClick={() => {
                                  setEditingItem(item.id);
                                  setResultValue(item.result_value ?? "");
                                  setResultFlag(
                                    item.abnormal_flag === "undetermined"
                                      ? "normal"
                                      : item.abnormal_flag,
                                  );
                                  setResultNotes(item.result_notes ?? "");
                                  setComponentValues({});
                                  setOrganism("");
                                  setAntibiogram("");
                                }}
                                className="neu-btn px-3 py-2 text-xs"
                              >
                                Lançar resultado
                              </button>
                              {item.result_value && (
                                <button
                                  onClick={() =>
                                    validateResult(order.id, item.id)
                                  }
                                  className="neu-btn-primary px-3 py-2 text-xs"
                                >
                                  Validar
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                      {editingItem === item.id && (
                        <ResultEditor
                          item={item}
                          resultValue={resultValue}
                          setResultValue={setResultValue}
                          resultFlag={resultFlag}
                          setResultFlag={setResultFlag}
                          resultNotes={resultNotes}
                          setResultNotes={setResultNotes}
                          componentValues={componentValues}
                          setComponentValues={setComponentValues}
                          organism={organism}
                          setOrganism={setOrganism}
                          antibiogram={antibiogram}
                          setAntibiogram={setAntibiogram}
                          saving={pendingAction === `result:${item.id}`}
                          onSave={() => saveResult(order.id, item.id)}
                        />
                      )}
                    </div>
                  ))}
                </div>
                <div className="border-t border-neu-app p-4">
                  <ImagingPanel labOrderId={order.id} />
                </div>
              </article>
            ))
          )}
          {!loading &&
            !error &&
            filteredOrders.length === 0 &&
            orders.length > 0 && (
              <div className="neu-panel p-8 text-center text-sm text-neu-inkSoft">
                Nenhum pedido corresponde aos filtros.
              </div>
            )}
          {!loading && !error && orders.length === 0 && (
            <div className="neu-panel p-10 text-center">
              <FlaskConical
                aria-hidden="true"
                className="mx-auto text-neu-inkMuted"
                size={30}
              />
              <p className="mt-3 font-medium text-neu-ink">
                Nenhum pedido laboratorial
              </p>
              <p className="text-sm text-neu-inkSoft">
                Crie o primeiro pedido para iniciar o fluxo.
              </p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
