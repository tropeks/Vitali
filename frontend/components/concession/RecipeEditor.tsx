'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import {
  unwrap,
  type Listish,
  type MaterialOption,
  type ServiceRecipe,
} from './contractMeta'

/**
 * RecipeEditor — insumo-per-exam recipe lines for a single ConcessionService.
 * Loads GET /api/v1/service-recipes/?service=<id>; adds lines via POST
 * (material + quantity per exam). Mirrors ServiceRecipeSerializer.
 */

const INPUT_CLASS =
  'border border-slate-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`

interface RecipeEditorProps {
  serviceId: string
  materials: MaterialOption[]
}

export default function RecipeEditor({ serviceId, materials }: RecipeEditorProps) {
  const [recipes, setRecipes] = useState<ServiceRecipe[]>([])
  const [loading, setLoading] = useState(true)
  const [material, setMaterial] = useState('')
  const [quantity, setQuantity] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiFetch<Listish<ServiceRecipe>>(
        `/api/v1/service-recipes/?service=${serviceId}`
      )
      setRecipes(unwrap(data))
    } catch {
      setRecipes([])
    } finally {
      setLoading(false)
    }
  }, [serviceId])

  useEffect(() => {
    load()
  }, [load])

  const materialName = useCallback(
    (id: string) => materials.find((m) => m.id === id)?.name ?? id,
    [materials]
  )

  async function addLine() {
    setSubmitting(true)
    try {
      await apiFetch('/api/v1/service-recipes/', {
        method: 'POST',
        body: JSON.stringify({
          service: serviceId,
          material,
          quantity: quantity.trim(),
        }),
      })
      setMaterial('')
      setQuantity('')
      await load()
    } catch {
      // swallow — surfaced by empty state; keep the form values
    } finally {
      setSubmitting(false)
    }
  }

  const valid = material !== '' && quantity.trim() !== ''

  return (
    <div className="mt-3">
      {loading && <p className="text-sm text-neu-inkMuted">Carregando receita...</p>}

      {!loading && recipes.length === 0 && (
        <p className="text-sm text-neu-inkMuted">Nenhum insumo cadastrado para este serviço.</p>
      )}

      {!loading && recipes.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {recipes.map((r) => (
            <li key={r.id} className="flex items-center justify-between py-1.5 text-sm">
              <span className="text-slate-700">{materialName(r.material)}</span>
              <span className="text-xs text-slate-500">{r.quantity} / exame</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          aria-label="Insumo da receita"
          className={SELECT_CLASS}
          value={material}
          onChange={(e) => setMaterial(e.target.value)}
        >
          <option value="">Selecione o insumo</option>
          {materials.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
              {m.unit_of_measure ? ` (${m.unit_of_measure})` : ''}
            </option>
          ))}
        </select>
        <input
          aria-label="Quantidade por exame"
          type="text"
          inputMode="decimal"
          placeholder="Qtd."
          className={`${INPUT_CLASS} w-24`}
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
        />
        <button
          type="button"
          onClick={addLine}
          disabled={!valid || submitting}
          className="rounded-lg bg-neu-brand px-3 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? '...' : '+ Adicionar insumo'}
        </button>
      </div>
    </div>
  )
}
