'use client'

/**
 * A8: Trigger a governed-terminology CSV import for one catalog (CBO/CNES/
 * LOINC/UCUM). POSTs multipart/form-data to
 * /api/v1/platform/terminology/<system>/import/ with a `file` field
 * (semicolon-delimited CSV) and an optional `version`.
 *
 * apiFetch only stringifies + sets `Content-Type: application/json` when the
 * body is a string — a FormData body passes through untouched, so the browser
 * sets the multipart boundary itself. That means apiFetch can be used as-is
 * here; no need to fall back to a direct fetch with a manual Bearer header.
 */
import { useState } from 'react'
import { X, Upload } from 'lucide-react'
import { apiFetch } from '@/lib/api'

interface ImportResult {
  status?: string
  created?: number
  updated?: number
  row_count?: number
  [key: string]: unknown
}

interface ImportModalProps {
  system: string
  label: string
  onClose: () => void
  onImported: () => void
}

export default function ImportModal({ system, label, onClose, onImported }: ImportModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [version, setVersion] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)

  async function handleSubmit() {
    if (!file) {
      setError('Selecione um arquivo CSV para importar.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      if (version.trim()) formData.append('version', version.trim())
      const data = await apiFetch<ImportResult>(`/api/v1/platform/terminology/${system}/import/`, {
        method: 'POST',
        body: formData,
      })
      setResult(data ?? {})
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro ao importar o arquivo.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-900">Importar CSV — {label}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-600 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-4 space-y-3">
          {result ? (
            <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
              <p className="font-semibold">Importação concluída</p>
              <p className="mt-1 text-xs">
                {result.created != null && `Criados: ${result.created} · `}
                {result.updated != null && `Atualizados: ${result.updated} · `}
                {result.row_count != null && `Linhas: ${result.row_count} · `}
                Status: {result.status ?? 'ok'}
              </p>
            </div>
          ) : (
            <>
              <div>
                <label htmlFor={`terminology-import-file-${system}`} className="block text-xs font-medium text-slate-600 mb-1">
                  Arquivo CSV (delimitado por ;)
                </label>
                <input
                  id={`terminology-import-file-${system}`}
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="w-full text-sm"
                />
              </div>
              <div>
                <label htmlFor={`terminology-import-version-${system}`} className="block text-xs font-medium text-slate-600 mb-1">
                  Versão (opcional)
                </label>
                <input
                  id={`terminology-import-version-${system}`}
                  type="text"
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                  placeholder="ex.: 2026.1"
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              {error && <p className="text-xs text-red-600">{error}</p>}
            </>
          )}
        </div>

        <div className="px-4 py-3 border-t border-slate-200 flex gap-2">
          {result ? (
            <button
              type="button"
              onClick={onImported}
              className="w-full text-sm font-semibold px-3 py-2.5 rounded-lg bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white hover:shadow-neu-btn-primary-hover"
            >
              Concluir
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                className="flex-1 inline-flex items-center justify-center gap-2 text-sm font-semibold px-3 py-2.5 rounded-lg bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white hover:shadow-neu-btn-primary-hover disabled:opacity-50"
              >
                <Upload size={15} />
                {submitting ? 'Importando...' : 'Importar'}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-2.5 text-sm text-slate-600 hover:text-slate-900"
              >
                Cancelar
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
