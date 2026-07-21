'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'

// Canonical importer column order (matches apps/pharmacy/services/formulary_import).
// Used to generate the downloadable template so a pharmacist always starts from a
// header the backend accepts.
const TEMPLATE_HEADER =
  'drug_name,drug_generic,strength_value,strength_unit,route,basis,dose_unit,' +
  'min_per_dose,max_per_dose,absolute_max_dose,min_per_kg,max_per_kg,max_per_day,' +
  'dose_role,enforcement,freq_min_per_day,freq_max_per_day,age_min_days,age_max_days,' +
  'weight_min_kg,weight_max_kg'

const TEMPLATE_BODY = [
  '# Modelo de formulário de doses — preencha uma linha por regra de dose.',
  '# Linhas iniciadas por # são comentários e são ignoradas na importação.',
  '# basis=fixed usa min_per_dose/max_per_dose; basis=per_kg usa min_per_kg/max_per_kg.',
  '# absolute_max_dose é sempre obrigatório (teto absoluto por administração).',
  '# enforcement=block (padrão) bloqueia dose fora da faixa; advise apenas alerta',
  '#   (opioides/sedativos sem teto rígido). Em branco = block.',
  TEMPLATE_HEADER,
  'Exemplo-Fixo,exemplo generico,10.000,mg,IV,fixed,mg,5,15,15,,,,maintenance,block,,,,,,',
  'Exemplo-PorKg,exemplo generico,40.000,mg,IV,per_kg,mg,,,700,5,7,,maintenance,advise,1,1,,,,',
].join('\n')

interface PreviewRow {
  line: number
  drug_name: string
  drug_generic: string
  strength: string
  route: string
  basis: string
  dose_role: string
  enforcement: string
  dose_unit: string
  therapeutic_band: string
  absolute_max_dose: string
  max_per_day: string
  age_band_days: string
  weight_band_kg: string
  freq_band_per_day: string
}

interface ImportSummary {
  row_count: number
  formularies_created: number
  formularies_updated: number
  rules_created: number
  rules_updated: number
  revalidation_required: number
}

interface PreviewResponse {
  rows: PreviewRow[]
  summary: ImportSummary
  errors: string[]
}

const PREVIEW_COLUMNS: { key: keyof PreviewRow; label: string }[] = [
  { key: 'line', label: 'Linha' },
  { key: 'drug_name', label: 'Medicamento' },
  { key: 'strength', label: 'Concentração' },
  { key: 'route', label: 'Via' },
  { key: 'basis', label: 'Base' },
  { key: 'dose_role', label: 'Regime' },
  { key: 'enforcement', label: 'Ação' },
  { key: 'therapeutic_band', label: 'Faixa terapêutica' },
  { key: 'absolute_max_dose', label: 'Teto absoluto' },
  { key: 'max_per_day', label: 'Máx/dia' },
  { key: 'age_band_days', label: 'Idade (dias)' },
  { key: 'weight_band_kg', label: 'Peso (kg)' },
  { key: 'freq_band_per_day', label: 'Freq/dia' },
]

function extractErrors(err: unknown): string[] {
  if (err instanceof ApiError && err.body) {
    const body = err.body as { errors?: string[]; detail?: string }
    if (Array.isArray(body.errors) && body.errors.length > 0) return body.errors
    if (body.detail) return [body.detail]
  }
  return ['Erro inesperado ao processar o arquivo. Tente novamente.']
}

export default function FormularioUploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [committed, setCommitted] = useState<{ message: string; summary: ImportSummary } | null>(
    null
  )
  const fileInputRef = useRef<HTMLInputElement>(null)

  function resetResults() {
    setPreview(null)
    setErrors([])
    setCommitted(null)
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null
    setFile(selected)
    resetResults()
  }

  function downloadTemplate() {
    const blob = new Blob([TEMPLATE_BODY], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'modelo-formulario-doses.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  async function handlePreview() {
    if (!file) return
    setBusy(true)
    resetResults()
    try {
      const formData = new FormData()
      formData.append('file', file)
      const data = await apiFetch<PreviewResponse>(
        '/api/v1/pharmacy/formulary/upload/preview/',
        { method: 'POST', body: formData }
      )
      setPreview(data)
    } catch (err) {
      setErrors(extractErrors(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleCommit() {
    if (!file) return
    setBusy(true)
    setErrors([])
    try {
      const formData = new FormData()
      formData.append('file', file)
      const data = await apiFetch<{ message: string; summary: ImportSummary }>(
        '/api/v1/pharmacy/formulary/upload/commit/',
        { method: 'POST', body: formData }
      )
      setCommitted(data)
      setPreview(null)
    } catch (err) {
      setErrors(extractErrors(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageShell variant="workbench" className="px-1 py-1">
      <div>
        <Link
          href="/configuracoes/farmacia/formulario"
          className="text-xs font-medium text-blue-600 hover:text-blue-500"
        >
          ← Voltar para validação de doses
        </Link>
        <h1 className="text-2xl font-semibold text-slate-900 mt-2">Importar formulário (doses)</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Carregue o CSV de doses de referência. Revise a pré-visualização e confirme. As regras
          importadas ficam <strong>pendentes de validação</strong> — assine cada uma na tela de
          validação antes de ativar o <code>dose_safety</code>.
        </p>
      </div>

      {/* Step 1 — file picker */}
      <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={handleFileChange}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
          >
            Escolher arquivo CSV
          </button>
          <span className="text-sm text-slate-600">
            {file ? file.name : 'Nenhum arquivo selecionado'}
          </span>
          <button
            type="button"
            onClick={downloadTemplate}
            className="ml-auto text-xs font-medium text-blue-600 hover:text-blue-500"
          >
            Baixar modelo CSV
          </button>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handlePreview}
            disabled={!file || busy}
            className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy && !committed ? 'Processando…' : 'Pré-visualizar'}
          </button>
        </div>
      </div>

      {/* Errors */}
      {errors.length > 0 && (
        <SectionState
          tone="critical"
          title={`${errors.length} problema(s) no arquivo — nada foi importado.`}
          detail="Corrija as linhas indicadas e tente novamente."
          action={
            <ul className="list-disc pl-5 space-y-1 text-xs">
              {errors.map((e, i) => (
                <li key={i} className="font-mono">
                  {e}
                </li>
              ))}
            </ul>
          }
        />
      )}

      {/* Commit success */}
      {committed && (
        <SectionState
          tone="success"
          title="Importação concluída."
          detail={committed.message}
          action={
            <Link
              href="/configuracoes/farmacia/formulario"
              className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500"
            >
              Ir para validação de doses
            </Link>
          }
        />
      )}

      {/* Step 2 — preview + confirm */}
      {preview && (
        <div className="space-y-3">
          <SectionState
            tone="neutral"
            title={`Pré-visualização: ${preview.summary.row_count} regra(s) no arquivo.`}
            detail={
              `Formulários: ${preview.summary.formularies_created} a criar, ` +
              `${preview.summary.formularies_updated} a atualizar · ` +
              `Regras: ${preview.summary.rules_created} a criar, ` +
              `${preview.summary.rules_updated} a atualizar. Confira antes de confirmar.`
            }
          />

          {preview.summary.revalidation_required > 0 && (
            <SectionState
              tone="warning"
              title={
                `${preview.summary.revalidation_required} regra(s) validada(s) ` +
                'terão valores alterados e voltarão a pendente.'
              }
              detail={
                'Os novos valores só entram em vigor no dose_safety depois que um ' +
                'farmacêutico assinar cada regra novamente na tela de validação.'
              }
            />
          )}

          <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
            <table className="w-full text-sm min-w-[1100px]">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  {PREVIEW_COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className="text-left px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500"
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.line} className="border-b border-slate-100 last:border-0">
                    {PREVIEW_COLUMNS.map((c) => (
                      <td
                        key={c.key}
                        className={`px-3 py-2.5 text-slate-600 text-xs ${
                          c.key === 'drug_name' ? 'font-medium text-slate-900' : ''
                        }`}
                      >
                        {row[c.key]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleCommit}
              disabled={busy}
              className="inline-flex items-center rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busy ? 'Importando…' : 'Confirmar importação'}
            </button>
            <button
              type="button"
              onClick={resetResults}
              disabled={busy}
              className="inline-flex items-center rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}
    </PageShell>
  )
}
