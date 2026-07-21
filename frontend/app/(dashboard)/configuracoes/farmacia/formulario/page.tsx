'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { apiFetch } from '@/lib/api'
import { Badge, Button, PageShell, SectionState } from '@/components/shared'

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
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Formulário (doses)</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Revise e valide as regras de dose antes que entrem em vigor.
          </p>
        </div>
        <Link
          href="/configuracoes/farmacia/formulario/upload"
          className="inline-flex items-center px-4 py-2 text-xs font-bold text-white bg-gradient-to-b from-neu-brand to-neu-brandDeep rounded-lg border-t border-neu-brandEdge shadow-neu-btn-primary hover:shadow-neu-btn-primary-hover transition-all"
        >
          Importar CSV
        </Link>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar regras de dose."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && rules.length === 0 && (
        <SectionState
          title="Nenhuma regra de dose cadastrada."
          detail="Adicione regras de dose no painel administrativo para que apareçam aqui."
        />
      )}

      {!loading && !error && rules.length > 0 && (
        <div className="bg-neu-panelAlt rounded-xl border border-white shadow-neu-panel overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead>
              <tr className="border-b border-white bg-neu-panel">
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
                    className="text-left px-4 py-3 text-xs font-semibold text-neu-inkSoft uppercase tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="border-b border-white last:border-0">
                  <td className="px-4 py-3 font-medium text-neu-ink">{rule.drug_name}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">{rule.basis}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">{rule.dose_unit}</td>
                  <td className="px-4 py-3 text-neu-inkSoft text-xs">{formatLimits(rule)}</td>
                  <td className="px-4 py-3">
                    {rule.active ? (
                      <Badge variant="success">Sim</Badge>
                    ) : (
                      <Badge variant="neutral">Não</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {rule.validated ? (
                      <Badge variant="success">Validada</Badge>
                    ) : (
                      <span className="inline-flex items-center rounded-full border border-yellow-200 bg-yellow-100 px-2.5 py-1 text-xs font-semibold text-yellow-800">
                        Pendente
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft text-xs">
                    {rule.validated && rule.validated_by
                      ? `${rule.validated_by}${rule.validated_at ? ' · ' + formatDate(rule.validated_at) : ''}`
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {!rule.validated ? (
                      <Button
                        type="button"
                        variant="primary"
                        onClick={() => handleValidar(rule.id)}
                        disabled={validatingId === rule.id}
                      >
                        {validatingId === rule.id ? 'Validando…' : 'Validar'}
                      </Button>
                    ) : (
                      <span className="text-xs text-neu-inkMuted">—</span>
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
