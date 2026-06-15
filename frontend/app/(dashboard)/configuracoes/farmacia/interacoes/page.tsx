'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'

interface AllergenClass {
  id: string
  name: string
  members: string
  description: string
  active: boolean
  source: string
  version: string
}

interface DrugInteraction {
  id: string
  ingredient_a: string
  ingredient_b: string
  severity: string
  severity_display: string
  active: boolean
  source: string
  version: string
}

export default function InteracoesPage() {
  const [allergenClasses, setAllergenClasses] = useState<AllergenClass[]>([])
  const [drugInteractions, setDrugInteractions] = useState<DrugInteraction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [togglingAllergenId, setTogglingAllergenId] = useState<string | null>(null)
  const [togglingInteractionId, setTogglingInteractionId] = useState<string | null>(null)

  const loadAllergenClasses = useCallback(async () => {
    const data = await apiFetch<AllergenClass[] | { results: AllergenClass[] }>(
      '/api/v1/pharmacy/allergen-classes/'
    )
    return Array.isArray(data) ? data : (data as { results: AllergenClass[] }).results ?? []
  }, [])

  const loadDrugInteractions = useCallback(async () => {
    const data = await apiFetch<DrugInteraction[] | { results: DrugInteraction[] }>(
      '/api/v1/pharmacy/drug-interactions/'
    )
    return Array.isArray(data) ? data : (data as { results: DrugInteraction[] }).results ?? []
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [classes, interactions] = await Promise.all([
        loadAllergenClasses(),
        loadDrugInteractions(),
      ])
      setAllergenClasses(classes)
      setDrugInteractions(interactions)
    } catch {
      setError('Erro ao carregar dados.')
    } finally {
      setLoading(false)
    }
  }, [loadAllergenClasses, loadDrugInteractions])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  async function handleToggleAllergen(row: AllergenClass) {
    setTogglingAllergenId(row.id)
    try {
      await apiFetch(`/api/v1/pharmacy/allergen-classes/${row.id}/set-active/`, {
        method: 'POST',
        body: JSON.stringify({ active: !row.active }),
      })
    } catch {
      // reload anyway to show current state
    } finally {
      setTogglingAllergenId(null)
    }
    try {
      const data = await apiFetch<AllergenClass[] | { results: AllergenClass[] }>(
        '/api/v1/pharmacy/allergen-classes/'
      )
      setAllergenClasses(Array.isArray(data) ? data : (data as { results: AllergenClass[] }).results ?? [])
    } catch {
      // ignore reload error
    }
  }

  async function handleToggleInteraction(row: DrugInteraction) {
    setTogglingInteractionId(row.id)
    try {
      await apiFetch(`/api/v1/pharmacy/drug-interactions/${row.id}/set-active/`, {
        method: 'POST',
        body: JSON.stringify({ active: !row.active }),
      })
    } catch {
      // reload anyway to show current state
    } finally {
      setTogglingInteractionId(null)
    }
    try {
      const data = await apiFetch<DrugInteraction[] | { results: DrugInteraction[] }>(
        '/api/v1/pharmacy/drug-interactions/'
      )
      setDrugInteractions(Array.isArray(data) ? data : (data as { results: DrugInteraction[] }).results ?? [])
    } catch {
      // ignore reload error
    }
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Interações</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Revise e ative as classes de reatividade cruzada e as interações medicamentosas.
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
          {/* ── Classes de reatividade cruzada ── */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold text-slate-800">
              Classes de reatividade cruzada
            </h2>

            {allergenClasses.length === 0 ? (
              <SectionState
                title="Nenhuma classe de reatividade cadastrada."
                detail="Adicione classes no painel administrativo para que apareçam aqui."
              />
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
                <table className="w-full text-sm min-w-[800px]">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50">
                      {['Nome', 'Membros', 'Descrição', 'Fonte/Versão', 'Ativo', 'Ação'].map((h) => (
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
                    {allergenClasses.map((row) => (
                      <tr key={row.id} className="border-b border-slate-100 last:border-0">
                        <td className="px-4 py-3 font-medium text-slate-900">{row.name}</td>
                        <td className="px-4 py-3 text-slate-600 text-xs">{row.members}</td>
                        <td className="px-4 py-3 text-slate-600 text-xs">{row.description}</td>
                        <td className="px-4 py-3 text-slate-600 text-xs">
                          {row.source} / {row.version}
                        </td>
                        <td className="px-4 py-3">
                          {row.active ? (
                            <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                              Sim
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                              Não
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleToggleAllergen(row)}
                            disabled={togglingAllergenId === row.id}
                            className={`inline-flex items-center rounded-md px-3 py-1.5 text-xs font-semibold text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed ${
                              row.active
                                ? 'bg-red-600 hover:bg-red-500'
                                : 'bg-blue-600 hover:bg-blue-500'
                            }`}
                          >
                            {togglingAllergenId === row.id
                              ? row.active
                                ? 'Desativando…'
                                : 'Ativando…'
                              : row.active
                              ? 'Desativar'
                              : 'Ativar'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ── Interações medicamentosas ── */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold text-slate-800">
              Interações medicamentosas
            </h2>

            {drugInteractions.length === 0 ? (
              <SectionState
                title="Nenhuma interação medicamentosa cadastrada."
                detail="Adicione interações no painel administrativo para que apareçam aqui."
              />
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
                <table className="w-full text-sm min-w-[800px]">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50">
                      {[
                        'Princípio A',
                        'Princípio B',
                        'Severidade',
                        'Fonte/Versão',
                        'Ativo',
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
                    {drugInteractions.map((row) => (
                      <tr key={row.id} className="border-b border-slate-100 last:border-0">
                        <td className="px-4 py-3 font-medium text-slate-900">{row.ingredient_a}</td>
                        <td className="px-4 py-3 text-slate-600">{row.ingredient_b}</td>
                        <td className="px-4 py-3 text-slate-600">{row.severity_display}</td>
                        <td className="px-4 py-3 text-slate-600 text-xs">
                          {row.source} / {row.version}
                        </td>
                        <td className="px-4 py-3">
                          {row.active ? (
                            <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                              Sim
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                              Não
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleToggleInteraction(row)}
                            disabled={togglingInteractionId === row.id}
                            className={`inline-flex items-center rounded-md px-3 py-1.5 text-xs font-semibold text-white shadow-sm disabled:opacity-50 disabled:cursor-not-allowed ${
                              row.active
                                ? 'bg-red-600 hover:bg-red-500'
                                : 'bg-blue-600 hover:bg-blue-500'
                            }`}
                          >
                            {togglingInteractionId === row.id
                              ? row.active
                                ? 'Desativando…'
                                : 'Ativando…'
                              : row.active
                              ? 'Desativar'
                              : 'Ativar'}
                          </button>
                        </td>
                      </tr>
                    ))}
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
