'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  formatBRL,
  unwrap,
  type Listish,
  type MaterialOption,
  type MaterialUnitCostRow,
} from './pnlMeta'

/**
 * MaterialCostEditor — CRUD over the concession-local material unit costs
 * (B0-T3). These figures drive the consumption leg of the P&L, so the editor
 * lives alongside the dashboard. Rows carry a bare material FK; names come from
 * the pharmacy materials list. Writes send { material, unit_cost }.
 */

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const PRIMARY_BTN =
  'rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50'
const GHOST_BTN =
  'rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100'

export default function MaterialCostEditor() {
  const [costs, setCosts] = useState<MaterialUnitCostRow[]>([])
  const [materials, setMaterials] = useState<MaterialOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [formError, setFormError] = useState('')

  // Add form.
  const [newMaterial, setNewMaterial] = useState('')
  const [newCost, setNewCost] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Inline edit.
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [savingId, setSavingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const [costData, matData] = await Promise.all([
        apiFetch<Listish<MaterialUnitCostRow>>('/api/v1/concession/material-unit-costs/'),
        apiFetch<Listish<MaterialOption>>('/api/v1/pharmacy/materials/'),
      ])
      setCosts(unwrap(costData))
      setMaterials(unwrap(matData))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const materialName = useMemo(() => {
    const map = new Map(materials.map((m) => [String(m.id), m.name]))
    return (id: string) => map.get(String(id)) ?? id
  }, [materials])

  async function handleCreate() {
    if (!newMaterial) return
    setSubmitting(true)
    setFormError('')
    try {
      await apiFetch('/api/v1/concession/material-unit-costs/', {
        method: 'POST',
        body: JSON.stringify({ material: newMaterial, unit_cost: newCost.trim() }),
      })
      setNewMaterial('')
      setNewCost('')
      await load()
    } catch (err) {
      setFormError(
        err instanceof ApiError ? 'Não foi possível salvar o custo.' : 'Erro de conexão.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  function startEdit(row: MaterialUnitCostRow) {
    setEditingId(row.id)
    setEditValue(row.unit_cost)
    setFormError('')
  }

  async function handleUpdate(row: MaterialUnitCostRow) {
    setSavingId(row.id)
    setFormError('')
    try {
      await apiFetch(`/api/v1/concession/material-unit-costs/${row.id}/`, {
        method: 'PUT',
        body: JSON.stringify({ material: row.material, unit_cost: editValue.trim() }),
      })
      setEditingId(null)
      await load()
    } catch (err) {
      setFormError(
        err instanceof ApiError ? 'Não foi possível atualizar o custo.' : 'Erro de conexão.'
      )
    } finally {
      setSavingId(null)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">Custos de material</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        Custo unitário local de cada material. Alimenta o custo de consumo apurado no P&L.
      </p>

      {error && (
        <div className="mt-3">
          <SectionState
            title="Erro ao carregar custos de material."
            detail="Verifique sua conexão e tente novamente."
            tone="critical"
          />
        </div>
      )}

      {loading && <p className="mt-3 text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && (
        <>
          {costs.length === 0 ? (
            <p className="mt-3 text-sm text-neu-inkMuted">Nenhum custo de material cadastrado ainda.</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
                    <th className="px-3 py-2">Material</th>
                    <th className="px-3 py-2 text-right">Custo unitário</th>
                    <th className="px-3 py-2 text-right">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {costs.map((row) => {
                    const name = materialName(row.material)
                    const isEditing = editingId === row.id
                    return (
                      <tr key={row.id} className="text-slate-700">
                        <td className="px-3 py-2 font-medium text-slate-900">{name}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {isEditing ? (
                            <input
                              aria-label={`Editar custo de ${name}`}
                              type="text"
                              inputMode="decimal"
                              className={`${INPUT_CLASS} w-28 text-right`}
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                            />
                          ) : (
                            formatBRL(row.unit_cost)
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {isEditing ? (
                            <div className="flex justify-end gap-2">
                              <button
                                type="button"
                                className={PRIMARY_BTN}
                                disabled={savingId === row.id}
                                onClick={() => handleUpdate(row)}
                              >
                                {savingId === row.id ? '...' : 'Salvar'}
                              </button>
                              <button
                                type="button"
                                className={GHOST_BTN}
                                onClick={() => setEditingId(null)}
                              >
                                Cancelar
                              </button>
                            </div>
                          ) : (
                            <button type="button" className={GHOST_BTN} onClick={() => startEdit(row)}>
                              Editar
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="mt-4 border-t border-slate-100 pt-4">
            {formError && <p className="mb-2 text-xs text-red-600">{formError}</p>}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-700">Material</span>
                <select
                  aria-label="Material"
                  className={SELECT_CLASS}
                  value={newMaterial}
                  onChange={(e) => setNewMaterial(e.target.value)}
                >
                  <option value="">Selecione o material</option>
                  {materials.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {m.unit_of_measure ? ` (${m.unit_of_measure})` : ''}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-700">Custo unitário</span>
                <input
                  aria-label="Custo unitário"
                  type="text"
                  inputMode="decimal"
                  placeholder="0,00"
                  className={INPUT_CLASS}
                  value={newCost}
                  onChange={(e) => setNewCost(e.target.value)}
                />
              </label>
              <button
                type="button"
                onClick={handleCreate}
                disabled={!newMaterial || submitting}
                className={PRIMARY_BTN}
              >
                {submitting ? 'Salvando...' : '+ Adicionar'}
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
