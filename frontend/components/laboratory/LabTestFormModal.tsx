"use client";

import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { Button, SectionState } from "@/components/shared";
import RemoteCombobox from "@/components/shared/RemoteCombobox";
import {
  categoryLabels,
  resultTypeLabels,
  type LabTest,
  type LoincResult,
} from "./types";

// A4-a — create/edit a lab-test catalog entry. Adds the governed LOINC picker
// (reuses the shared RemoteCombobox against /api/v1/terminology/loinc/?q=) and
// the delta_threshold_pct control. Save PATCHes an existing test or POSTs a new
// one; loinc_code goes up as a plain string, delta_threshold_pct as a decimal
// string or null (null/empty = delta check inert).

interface Props {
  /** null → create a new test; otherwise edit the given one. */
  test: LabTest | null;
  onClose: () => void;
  onSaved: (test: LabTest) => void;
}

// Until the user searches, show the stored code as its own label (no cached
// display text) — a search + pick replaces it with the catalog's `display`.
function initialLoinc(code: string | null | undefined): LoincResult | null {
  if (!code) return null;
  return { system: "loinc", code, display: code, active: true, context: null };
}

function loincLabel(item: LoincResult): string {
  return item.display && item.display !== item.code
    ? `${item.code} — ${item.display}`
    : item.code;
}

const categoryOptions = Object.entries(categoryLabels);
const resultTypeOptions = Object.entries(resultTypeLabels);

export default function LabTestFormModal({ test, onClose, onSaved }: Props) {
  const [code, setCode] = useState(test?.code ?? "");
  const [name, setName] = useState(test?.name ?? "");
  const [category, setCategory] = useState(test?.category ?? "other");
  const [resultType, setResultType] = useState(test?.result_type ?? "numeric");
  const [specimenType, setSpecimenType] = useState(test?.specimen_type ?? "");
  const [unit, setUnit] = useState(test?.unit ?? "");
  const [referenceRange, setReferenceRange] = useState(
    test?.reference_range ?? "",
  );
  const [method, setMethod] = useState(test?.method ?? "");
  const [loinc, setLoinc] = useState<LoincResult | null>(
    initialLoinc(test?.loinc_code),
  );
  const [deltaThreshold, setDeltaThreshold] = useState(
    test?.delta_threshold_pct ?? "",
  );
  const [active, setActive] = useState(test?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const trimmedDelta = deltaThreshold.trim();
    const payload = {
      code: code.trim(),
      name: name.trim(),
      category,
      result_type: resultType,
      specimen_type: specimenType.trim(),
      unit: unit.trim(),
      reference_range: referenceRange.trim(),
      method: method.trim(),
      loinc_code: loinc?.code ?? "",
      delta_threshold_pct: trimmedDelta === "" ? null : trimmedDelta,
      active,
    };
    try {
      const saved = await apiFetch<LabTest>(
        test ? `/api/v1/lab-tests/${test.id}/` : "/api/v1/lab-tests/",
        {
          method: test ? "PATCH" : "POST",
          body: JSON.stringify(payload),
        },
      );
      onSaved(saved);
    } catch {
      setError("Não foi possível salvar o exame. Tente novamente.");
    } finally {
      setSaving(false);
    }
  }

  const inputClass = "neu-input mt-1 w-full px-3 py-2 text-sm font-normal";
  const labelClass =
    "block text-[11px] font-bold uppercase tracking-wide text-neu-inkSoft";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-neu-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-neu-app px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-neu-ink">
              {test ? "Editar exame" : "Novo exame"}
            </h2>
            <p className="mt-0.5 text-xs text-neu-inkMuted">
              Catálogo laboratorial · LOINC e delta-check
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:text-slate-700"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className={labelClass}>
              Código *
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                className={inputClass}
              />
            </label>
            <label className={labelClass}>
              Nome *
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className={inputClass}
              />
            </label>
            <label className={labelClass}>
              Categoria
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className={inputClass}
              >
                {categoryOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className={labelClass}>
              Tipo de resultado
              <select
                value={resultType}
                onChange={(e) => setResultType(e.target.value)}
                className={inputClass}
              >
                {resultTypeOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className={labelClass}>
              Material biológico
              <input
                value={specimenType}
                onChange={(e) => setSpecimenType(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className={labelClass}>
              Método
              <input
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className={labelClass}>
              Unidade
              <input
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className={labelClass}>
              Valor de referência
              <input
                value={referenceRange}
                onChange={(e) => setReferenceRange(e.target.value)}
                className={inputClass}
              />
            </label>
          </div>

          <div>
            <span className={labelClass}>Código LOINC</span>
            <div className="mt-1">
              <RemoteCombobox<LoincResult>
                label="LOINC"
                endpoint="/api/v1/terminology/loinc/"
                queryParam="q"
                value={loinc}
                getKey={(item) => item.code}
                getLabel={loincLabel}
                onChange={setLoinc}
                placeholder="Buscar termo LOINC..."
              />
            </div>
            <p className="mt-1 text-xs text-neu-inkMuted">
              Vincula o exame ao catálogo LOINC para interoperabilidade (FHIR).
            </p>
          </div>

          <div>
            <label className={labelClass} htmlFor="delta-threshold">
              Limiar de delta-check (%)
            </label>
            <input
              id="delta-threshold"
              type="number"
              step="0.01"
              min="0"
              inputMode="decimal"
              value={deltaThreshold}
              onChange={(e) => setDeltaThreshold(e.target.value)}
              placeholder="Ex.: 20"
              className={inputClass}
            />
            <p className="mt-1 text-xs text-neu-inkMuted">
              Variação percentual em relação ao resultado anterior que dispara um
              alerta. Vazio = delta-check desligado.
            </p>
          </div>

          <label className="flex items-center gap-2 text-sm text-neu-ink">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
            />
            Exame ativo no catálogo
          </label>

          {error && (
            <SectionState title="Erro ao salvar." detail={error} tone="critical" />
          )}

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={onClose}
              className="flex-1"
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={saving || !code.trim() || !name.trim()}
              className="flex-1"
            >
              {saving ? "Salvando..." : "Salvar"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
