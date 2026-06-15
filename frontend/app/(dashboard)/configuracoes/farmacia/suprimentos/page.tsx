'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'

interface Drug {
  id: string
  name: string
  is_active: boolean
  is_controlled: boolean
  lead_time_days: number | null
  safety_stock: string | null
  reorder_point: string | null
  min_refill_interval_days: number | null
}

interface Material {
  id: string
  name: string
  is_active: boolean
  lead_time_days: number | null
  safety_stock: string | null
  reorder_point: string | null
}

// Per-row edit state stored as strings; blank string means "will send null"
interface DrugEditState {
  lead_time_days: string
  safety_stock: string
  reorder_point: string
  min_refill_interval_days: string
}

interface MaterialEditState {
  lead_time_days: string
  safety_stock: string
  reorder_point: string
}

function drugToEditState(drug: Drug): DrugEditState {
  return {
    lead_time_days: drug.lead_time_days != null ? String(drug.lead_time_days) : '',
    safety_stock: drug.safety_stock ?? '',
    reorder_point: drug.reorder_point ?? '',
    min_refill_interval_days:
      drug.min_refill_interval_days != null ? String(drug.min_refill_interval_days) : '',
  }
}

function materialToEditState(mat: Material): MaterialEditState {
  return {
    lead_time_days: mat.lead_time_days != null ? String(mat.lead_time_days) : '',
    safety_stock: mat.safety_stock ?? '',
    reorder_point: mat.reorder_point ?? '',
  }
}

/** Convert string edit value to payload value: blank → null, non-blank stays as-is for decimals */
function toPayloadValue(val: string, isInt: boolean): number | string | null {
  if (val.trim() === '') return null
  if (isInt) return parseInt(val, 10)
  return val
}

export default function SuprimentosPage() {
  const [drugs, setDrugs] = useState<Drug[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Per-row local edit state: keyed by id
  const [drugEdits, setDrugEdits] = useState<Record<string, DrugEditState>>({})
  const [materialEdits, setMaterialEdits] = useState<Record<string, MaterialEditState>>({})

  const [savingId, setSavingId] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [drugsData, materialsData] = await Promise.all([
        apiFetch<Drug[] | { results: Drug[] }>('/api/v1/pharmacy/drugs/'),
        apiFetch<Material[] | { results: Material[] }>('/api/v1/pharmacy/materials/'),
      ])

      const drugList = Array.isArray(drugsData)
        ? drugsData
        : (drugsData as { results: Drug[] }).results ?? []
      const materialList = Array.isArray(materialsData)
        ? materialsData
        : (materialsData as { results: Material[] }).results ?? []

      setDrugs(drugList)
      setMaterials(materialList)

      // Initialize edit state from loaded data
      const newDrugEdits: Record<string, DrugEditState> = {}
      for (const drug of drugList) {
        newDrugEdits[drug.id] = drugToEditState(drug)
      }
      setDrugEdits(newDrugEdits)

      const newMaterialEdits: Record<string, MaterialEditState> = {}
      for (const mat of materialList) {
        newMaterialEdits[mat.id] = materialToEditState(mat)
      }
      setMaterialEdits(newMaterialEdits)
    } catch {
      setError('Erro ao carregar dados.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  async function handleSaveDrug(drug: Drug) {
    setSavingId(drug.id)
    const edit = drugEdits[drug.id]
    if (!edit) return
    const payload: Record<string, number | string | null> = {
      lead_time_days: toPayloadValue(edit.lead_time_days, true),
      safety_stock: toPayloadValue(edit.safety_stock, false),
      reorder_point: toPayloadValue(edit.reorder_point, false),
    }
    if (drug.is_controlled) {
      payload.min_refill_interval_days = toPayloadValue(edit.min_refill_interval_days, true)
    }
    try {
      await apiFetch(`/api/v1/pharmacy/drugs/${drug.id}/`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      })
    } catch {
      // ignore; reload anyway to reflect current state
    } finally {
      setSavingId(null)
    }
    await loadAll()
  }

  async function handleSaveMaterial(mat: Material) {
    setSavingId(mat.id)
    const edit = materialEdits[mat.id]
    if (!edit) return
    const payload: Record<string, number | string | null> = {
      lead_time_days: toPayloadValue(edit.lead_time_days, true),
      safety_stock: toPayloadValue(edit.safety_stock, false),
      reorder_point: toPayloadValue(edit.reorder_point, false),
    }
    try {
      await apiFetch(`/api/v1/pharmacy/materials/${mat.id}/`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      })
    } catch {
      // ignore; reload anyway
    } finally {
      setSavingId(null)
    }
    await loadAll()
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Suprimentos</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Configure os parâmetros de reposição e estoque de segurança de medicamentos e materiais.
        </p>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar dados."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-slate-500">Carregando...</p>}

      {!loading && !error && (
        <>
          {/* ── Medicamentos ── */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold text-slate-800">Medicamentos</h2>

            {drugs.length === 0 ? (
              <SectionState
                title="Nenhum medicamento cadastrado."
                detail="Adicione medicamentos no painel administrativo para que apareçam aqui."
              />
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
                <table className="w-full text-sm min-w-[900px]">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50">
                      {[
                        'Medicamento',
                        'Tempo de reposição (dias)',
                        'Estoque de segurança',
                        'Ponto de reposição',
                        'Intervalo mínimo de reabastecimento (dias)',
                        'Ação',
                      ].map((h) => (
                        <th
                          key={h}
                          className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {drugs.map((drug) => {
                      const edit = drugEdits[drug.id] ?? drugToEditState(drug)
                      return (
                        <tr key={drug.id} className="border-b border-slate-100 last:border-0">
                          <td className="px-4 py-3 font-medium text-slate-900">{drug.name}</td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              data-testid={`lead_time_days-${drug.id}`}
                              value={edit.lead_time_days}
                              onChange={(e) =>
                                setDrugEdits((prev) => ({
                                  ...prev,
                                  [drug.id]: { ...edit, lead_time_days: e.target.value },
                                }))
                              }
                              className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="—"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              step="0.01"
                              data-testid={`safety_stock-${drug.id}`}
                              value={edit.safety_stock}
                              onChange={(e) =>
                                setDrugEdits((prev) => ({
                                  ...prev,
                                  [drug.id]: { ...edit, safety_stock: e.target.value },
                                }))
                              }
                              className="w-28 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="—"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              step="0.01"
                              data-testid={`reorder_point-${drug.id}`}
                              value={edit.reorder_point}
                              onChange={(e) =>
                                setDrugEdits((prev) => ({
                                  ...prev,
                                  [drug.id]: { ...edit, reorder_point: e.target.value },
                                }))
                              }
                              className="w-28 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="—"
                            />
                          </td>
                          <td className="px-4 py-3">
                            {drug.is_controlled ? (
                              <input
                                type="number"
                                data-testid={`min_refill_interval_days-${drug.id}`}
                                value={edit.min_refill_interval_days}
                                onChange={(e) =>
                                  setDrugEdits((prev) => ({
                                    ...prev,
                                    [drug.id]: {
                                      ...edit,
                                      min_refill_interval_days: e.target.value,
                                    },
                                  }))
                                }
                                className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                                placeholder="—"
                              />
                            ) : (
                              <span className="text-xs text-slate-400">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <button
                              onClick={() => handleSaveDrug(drug)}
                              disabled={savingId === drug.id}
                              className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {savingId === drug.id ? 'Salvando…' : 'Salvar'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ── Materiais ── */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold text-slate-800">Materiais</h2>

            {materials.length === 0 ? (
              <SectionState
                title="Nenhum material cadastrado."
                detail="Adicione materiais no painel administrativo para que apareçam aqui."
              />
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
                <table className="w-full text-sm min-w-[700px]">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50">
                      {[
                        'Material',
                        'Tempo de reposição (dias)',
                        'Estoque de segurança',
                        'Ponto de reposição',
                        'Ação',
                      ].map((h) => (
                        <th
                          key={h}
                          className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {materials.map((mat) => {
                      const edit = materialEdits[mat.id] ?? materialToEditState(mat)
                      return (
                        <tr key={mat.id} className="border-b border-slate-100 last:border-0">
                          <td className="px-4 py-3 font-medium text-slate-900">{mat.name}</td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              data-testid={`lead_time_days-${mat.id}`}
                              value={edit.lead_time_days}
                              onChange={(e) =>
                                setMaterialEdits((prev) => ({
                                  ...prev,
                                  [mat.id]: { ...edit, lead_time_days: e.target.value },
                                }))
                              }
                              className="w-24 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="—"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              step="0.01"
                              data-testid={`safety_stock-${mat.id}`}
                              value={edit.safety_stock}
                              onChange={(e) =>
                                setMaterialEdits((prev) => ({
                                  ...prev,
                                  [mat.id]: { ...edit, safety_stock: e.target.value },
                                }))
                              }
                              className="w-28 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="—"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              type="number"
                              step="0.01"
                              data-testid={`reorder_point-${mat.id}`}
                              value={edit.reorder_point}
                              onChange={(e) =>
                                setMaterialEdits((prev) => ({
                                  ...prev,
                                  [mat.id]: { ...edit, reorder_point: e.target.value },
                                }))
                              }
                              className="w-28 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                              placeholder="—"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <button
                              onClick={() => handleSaveMaterial(mat)}
                              disabled={savingId === mat.id}
                              className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {savingId === mat.id ? 'Salvando…' : 'Salvar'}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </PageShell>
  )
}
