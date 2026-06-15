'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'

interface DoseRule {
  id: string
  drug_name: string
  basis: string
  dose_unit: string
  min_per_kg: number | null
  max_per_kg: number | null
  min_per_dose: number | null
  max_per_dose: number | null
  absolute_max_dose: number | null
  active: boolean
  validated: boolean
  validated_by: string | null
  validated_at: string | null
}

function formatLimits(rule: DoseRule): string {
  const parts: string[] = []
  if (rule.min_per_kg != null || rule.max_per_kg != null) {
    const min = rule.min_per_kg ?? '–'
    const max = rule.max_per_kg ?? '–'
    parts.push(`${min}–${max} ${rule.dose_unit}/kg`)
  }
  if (rule.min_per_dose != null || rule.max_per_dose != null) {
    const min = rule.min_per_dose ?? '–'
    const max = rule.max_per_dose ?? '–'
    parts.push(`${min}–${max} ${rule.dose_unit}/dose`)
  }
  if (rule.absolute_max_dose != null) {
    parts.push(`máx ${rule.absolute_max_dose} ${rule.dose_unit}`)
  }
  return parts.join(' · ') || '—'
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

export default function FormularioPage() {
  const [rules, setRules] = useState<DoseRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [validatingId, setValidatingId] = useState<string | null>(null)

  const loadRules = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<DoseRule[] | { results: DoseRule[] }>(
        '/api/v1/pharmacy/dose-rules/'
      )
      setRules(Array.isArray(data) ? data : (data as { results: DoseRule[] }).results ?? [])
    } catch {
      setError('Erro ao carregar regras de dose.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRules()
  }, [loadRules])

  async function handleValidar(id: string) {
    setValidatingId(id)
    try {
      await apiFetch(`/api/v1/pharmacy/dose-rules/${id}/validate/`, { method: 'POST' })
    } catch {
      // 409 already-validated or other error — reload anyway to show current state
    } finally {
      setValidatingId(null)
    }
    await loadRules()
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Formulário (doses)</h1>
        <p className="text-sm text-slate-500 mt-0.5">
          Revise e valide as regras de dose antes que entrem em vigor.
        </p>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar regras de dose."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-slate-500">Carregando...</p>}

      {!loading && !error && rules.length === 0 && (
        <SectionState
          title="Nenhuma regra de dose cadastrada."
          detail="Adicione regras de dose no painel administrativo para que apareçam aqui."
        />
      )}

      {!loading && !error && rules.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {[
                  'Medicamento',
                  'Base',
                  'Unidade',
                  'Limites',
                  'Ativo',
                  'Validada',
                  'Validada por/em',
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
              {rules.map((rule) => (
                <tr key={rule.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 font-medium text-slate-900">{rule.drug_name}</td>
                  <td className="px-4 py-3 text-slate-600">{rule.basis}</td>
                  <td className="px-4 py-3 text-slate-600">{rule.dose_unit}</td>
                  <td className="px-4 py-3 text-slate-600 text-xs">{formatLimits(rule)}</td>
                  <td className="px-4 py-3">
                    {rule.active ? (
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
                    {rule.validated ? (
                      <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                        Validada
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700">
                        Pendente
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600 text-xs">
                    {rule.validated && rule.validated_by
                      ? `${rule.validated_by}${rule.validated_at ? ' · ' + formatDate(rule.validated_at) : ''}`
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {!rule.validated ? (
                      <button
                        onClick={() => handleValidar(rule.id)}
                        disabled={validatingId === rule.id}
                        className="inline-flex items-center rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {validatingId === rule.id ? 'Validando…' : 'Validar'}
                      </button>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  )
}
