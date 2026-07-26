'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'

/**
 * Governed patient problem list (FHIR Condition-style).
 * Backend: emr.ProblemListItem via GET /api/v1/problems/?patient=<id>
 * (emr module, emr.read). Prefer this governed surface over the legacy
 * ``medical_history`` field on the patient record.
 */

interface ProblemListItem {
  id: string
  condition: string
  cid10_code?: string | null
  cid_unmatched?: boolean | null
  clinical_status: string
  clinical_status_display?: string | null
  verification_status?: string | null
  verification_status_display?: string | null
  onset_date?: string | null
  abatement_date?: string | null
  notes?: string | null
}

interface ListResponse {
  results?: ProblemListItem[]
  count?: number
}

const CLINICAL_STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  active: { label: 'Ativo', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
  inactive: { label: 'Inativo', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  resolved: { label: 'Resolvido', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
}

const STATUS_ORDER: Record<string, number> = { active: 0, inactive: 1, resolved: 2 }

function normalizeList(payload: ListResponse | ProblemListItem[] | null | undefined): ProblemListItem[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

function formatDate(value?: string | null) {
  if (!value) return null
  return new Date(`${value}T00:00:00`).toLocaleDateString('pt-BR')
}

export default function ProblemList({ patientId }: { patientId: string }) {
  const [items, setItems] = useState<ProblemListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    if (!patientId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse | ProblemListItem[]>(
        `/api/v1/problems/?patient=${patientId}`
      )
      setItems(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId])

  useEffect(() => {
    load()
  }, [load])

  const sorted = useMemo(
    () =>
      [...items].sort(
        (a, b) => (STATUS_ORDER[a.clinical_status] ?? 9) - (STATUS_ORDER[b.clinical_status] ?? 9)
      ),
    [items]
  )

  if (loading) {
    return <SectionState title="Carregando problemas..." detail="Buscando a lista de problemas governada." />
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar problemas"
        detail="Não foi possível carregar a lista de problemas. Tente novamente."
        tone="critical"
        action={
          <button
            onClick={load}
            className="inline-flex items-center gap-2 text-xs font-semibold text-red-700 hover:underline"
          >
            <RefreshCw size={13} />
            Tentar novamente
          </button>
        }
      />
    )
  }

  if (sorted.length === 0) {
    return (
      <SectionState
        title="Sem problemas na lista"
        detail="Problemas ativos e resolvidos com CID-10 aparecerão aqui como contexto clínico governado."
      />
    )
  }

  return (
    <div className="space-y-2">
      {sorted.map((problem) => {
        const meta = CLINICAL_STATUS_META[problem.clinical_status] ?? {
          label: problem.clinical_status_display ?? problem.clinical_status,
          badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
        }
        const onset = formatDate(problem.onset_date)
        const abatement = formatDate(problem.abatement_date)
        return (
          <div key={problem.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Activity size={15} className="shrink-0 text-blue-600" />
                  <p className="text-sm font-semibold text-slate-900">{problem.condition}</p>
                </div>
                <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                  <span className="font-mono">
                    {problem.cid10_code ? `CID-10 ${problem.cid10_code}` : 'Sem CID-10'}
                  </span>
                  {problem.cid_unmatched && (
                    <span className="inline-flex rounded-full border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-[11px] font-semibold text-yellow-800">
                      não reconciliado
                    </span>
                  )}
                  {problem.verification_status_display && (
                    <span>| {problem.verification_status_display}</span>
                  )}
                </p>
              </div>
              <StatusBadge meta={meta} />
            </div>
            {(onset || abatement) && (
              <p className="mt-2 text-xs text-slate-500">
                {onset && `Início: ${onset}`}
                {onset && abatement && ' | '}
                {abatement && `Resolução: ${abatement}`}
              </p>
            )}
            {problem.notes && <p className="mt-2 text-sm text-slate-600">{problem.notes}</p>}
          </div>
        )
      })}
    </div>
  )
}
