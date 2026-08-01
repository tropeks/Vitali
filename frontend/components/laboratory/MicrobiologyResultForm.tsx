'use client'

import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { ANTIBIOGRAM_OPTIONS, CULTURE_RESULT_OPTIONS } from './especializado-types'

interface Props {
  orderItemId: string
  onCreated: () => void
  onCancel: () => void
}

interface AbxRow {
  antibiotic: string
  interpretation: string
}
interface OrganismRow {
  organism_name: string
  colony_count: string
  antibiogram: AbxRow[]
}

const emptyOrganism = (): OrganismRow => ({ organism_name: '', colony_count: '', antibiogram: [] })

/**
 * Lançar resultado de microbiologia (emr.write): cultura + organismos isolados +
 * antibiograma (S/I/R), tudo em um POST /microbiology-results/ (organisms_input,
 * árvore nested). O backend cria a árvore atomicamente e enforça emr.write.
 */
export default function MicrobiologyResultForm({ orderItemId, onCreated, onCancel }: Props) {
  const [cultureResult, setCultureResult] = useState('pendente')
  const [specimen, setSpecimen] = useState('')
  const [organisms, setOrganisms] = useState<OrganismRow[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function updateOrganism(i: number, patch: Partial<OrganismRow>) {
    setOrganisms((prev) => prev.map((o, idx) => (idx === i ? { ...o, ...patch } : o)))
  }
  function updateAbx(oi: number, ai: number, patch: Partial<AbxRow>) {
    setOrganisms((prev) =>
      prev.map((o, idx) =>
        idx === oi
          ? { ...o, antibiogram: o.antibiogram.map((a, j) => (j === ai ? { ...a, ...patch } : a)) }
          : o,
      ),
    )
  }

  async function submit() {
    setSubmitting(true)
    setError(null)
    const organisms_input = organisms
      .filter((o) => o.organism_name.trim())
      .map((o) => ({
        organism_name: o.organism_name.trim(),
        colony_count: o.colony_count.trim(),
        antibiogram: o.antibiogram
          .filter((a) => a.antibiotic.trim())
          .map((a) => ({ antibiotic: a.antibiotic.trim(), interpretation: a.interpretation })),
      }))
    try {
      await apiFetch('/api/v1/microbiology-results/', {
        method: 'POST',
        body: JSON.stringify({
          order_item: orderItemId,
          culture_result: cultureResult,
          specimen: specimen.trim(),
          organisms_input,
        }),
      })
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
        setError('Não foi possível salvar — talvez já exista um resultado para este pedido.')
        return
      }
      setError('Não foi possível salvar o resultado. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls =
    'w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm text-neu-ink'

  return (
    <div className="space-y-4 rounded-lg border border-blue-200 bg-blue-50/40 p-4">
      <h4 className="text-sm font-semibold text-neu-ink">Novo resultado de microbiologia</h4>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Resultado da cultura</span>
          <select
            aria-label="Resultado da cultura"
            value={cultureResult}
            onChange={(e) => setCultureResult(e.target.value)}
            className={inputCls}
          >
            {CULTURE_RESULT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Espécime</span>
          <input
            aria-label="Espécime"
            value={specimen}
            onChange={(e) => setSpecimen(e.target.value)}
            className={inputCls}
            placeholder="Ex.: urocultura"
          />
        </label>
      </div>

      {organisms.map((org, oi) => (
        <div key={oi} className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
          <div className="flex items-center gap-2">
            <input
              aria-label={`Organismo ${oi + 1}`}
              value={org.organism_name}
              onChange={(e) => updateOrganism(oi, { organism_name: e.target.value })}
              className={inputCls}
              placeholder="Organismo isolado (ex.: Escherichia coli)"
            />
            <input
              aria-label={`Contagem ${oi + 1}`}
              value={org.colony_count}
              onChange={(e) => updateOrganism(oi, { colony_count: e.target.value })}
              className="w-40 rounded-md border border-slate-300 bg-neu-input px-2 py-2 text-sm"
              placeholder="UFC/mL"
            />
            <button
              type="button"
              aria-label={`Remover organismo ${oi + 1}`}
              onClick={() => setOrganisms((p) => p.filter((_, i) => i !== oi))}
              className="text-red-600 hover:text-red-800"
            >
              <Trash2 size={16} />
            </button>
          </div>

          {org.antibiogram.map((abx, ai) => (
            <div key={ai} className="ml-4 flex items-center gap-2">
              <input
                aria-label={`Antibiótico ${oi + 1}-${ai + 1}`}
                value={abx.antibiotic}
                onChange={(e) => updateAbx(oi, ai, { antibiotic: e.target.value })}
                className={inputCls}
                placeholder="Antibiótico"
              />
              <select
                aria-label={`Interpretação ${oi + 1}-${ai + 1}`}
                value={abx.interpretation}
                onChange={(e) => updateAbx(oi, ai, { interpretation: e.target.value })}
                className="w-56 rounded-md border border-slate-300 bg-neu-input px-2 py-2 text-sm"
              >
                {ANTIBIOGRAM_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-label={`Remover antibiótico ${oi + 1}-${ai + 1}`}
                onClick={() =>
                  updateOrganism(oi, { antibiogram: org.antibiogram.filter((_, j) => j !== ai) })
                }
                className="text-red-600 hover:text-red-800"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              updateOrganism(oi, { antibiogram: [...org.antibiogram, { antibiotic: '', interpretation: 'S' }] })
            }
            className="ml-4 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline"
          >
            <Plus size={13} /> Antibiótico
          </button>
        </div>
      ))}

      <button
        type="button"
        onClick={() => setOrganisms((p) => [...p, emptyOrganism()])}
        className="inline-flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline"
      >
        <Plus size={15} /> Adicionar organismo
      </button>

      {error && <p className="text-sm font-semibold text-red-700">{error}</p>}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-panel"
        >
          Cancelar
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? 'Salvando...' : 'Salvar resultado'}
        </button>
      </div>
    </div>
  )
}
