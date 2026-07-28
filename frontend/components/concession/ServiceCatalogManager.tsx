'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import { unwrap, type ConcessionService, type Listish } from './contractMeta'

/**
 * ServiceCatalogManager — a compact list + inline create form for the
 * ConcessionService catalog (exams that can be priced/billed). Mirrors
 * ConcessionServiceSerializer writable fields.
 */

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'

export default function ServiceCatalogManager() {
  const [services, setServices] = useState<ConcessionService[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [modality, setModality] = useState('')
  const [tuss, setTuss] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<Listish<ConcessionService>>('/api/v1/concession/services/')
      setServices(unwrap(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate() {
    setSubmitting(true)
    setFormError('')
    try {
      await apiFetch<ConcessionService>('/api/v1/concession/services/', {
        method: 'POST',
        body: JSON.stringify({
          code: code.trim(),
          name: name.trim(),
          modality: modality.trim(),
          tuss_code: tuss.trim(),
          active: true,
        }),
      })
      setCode('')
      setName('')
      setModality('')
      setTuss('')
      load()
    } catch (err) {
      setFormError(
        err instanceof ApiError ? 'Não foi possível criar o serviço.' : 'Erro de conexão.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  const valid = code.trim().length > 0 && name.trim().length > 0

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">Catálogo de serviços</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        Exames concessionados disponíveis para precificação e receita.
      </p>

      {error && (
        <div className="mt-3">
          <SectionState
            title="Erro ao carregar serviços."
            detail="Tente novamente."
            tone="critical"
          />
        </div>
      )}

      {loading && <p className="mt-3 text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && services.length === 0 && (
        <p className="mt-3 text-sm text-neu-inkMuted">Nenhum serviço cadastrado ainda.</p>
      )}

      {!loading && !error && services.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100">
          {services.map((s) => (
            <li key={s.id} className="flex items-center justify-between py-2 text-sm">
              <span className="text-slate-700">
                <span className="font-medium text-slate-900">{s.code}</span> — {s.name}
              </span>
              <span className="text-xs text-slate-400">
                {s.modality || '—'}
                {s.tuss_code ? ` · TUSS ${s.tuss_code}` : ''}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 border-t border-slate-100 pt-4">
        {formError && <p className="mb-2 text-xs text-red-600">{formError}</p>}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <input
            aria-label="Código do serviço"
            placeholder="Código"
            className={INPUT_CLASS}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <input
            aria-label="Nome do serviço"
            placeholder="Nome"
            className={INPUT_CLASS}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            aria-label="Modalidade do serviço"
            placeholder="Modalidade"
            className={INPUT_CLASS}
            value={modality}
            onChange={(e) => setModality(e.target.value)}
          />
          <input
            aria-label="Código TUSS"
            placeholder="TUSS"
            className={INPUT_CLASS}
            value={tuss}
            onChange={(e) => setTuss(e.target.value)}
          />
        </div>
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={handleCreate}
            disabled={!valid || submitting}
            className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Salvando...' : '+ Novo serviço'}
          </button>
        </div>
      </div>
    </section>
  )
}
