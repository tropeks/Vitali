'use client'

import { useCallback, useEffect, useState } from 'react'
import { ClipboardCheck, RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'

/**
 * Governed medication reconciliation surface (maker-checker; read-only here).
 * Backend: emr.MedicationReconciliation via
 * GET /api/v1/medication-reconciliations/?patient=<id> (emr module, emr.read).
 * Each reconciliation is a per-transition (admission/transfer/discharge) event
 * carrying immutable per-medication decisions once concluded.
 */

interface ReconciliationItem {
  id: string
  medication_name: string
  home_dosage?: string | null
  action: string
  action_display?: string | null
  reason?: string | null
}

interface Reconciliation {
  id: string
  encounter?: string | null
  moment: string
  moment_display?: string | null
  status: string
  status_display?: string | null
  notes?: string | null
  completed_at?: string | null
  created_at?: string | null
  items?: ReconciliationItem[]
}

interface ListResponse {
  results?: Reconciliation[]
  count?: number
}

const STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  draft: { label: 'Rascunho', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  completed: { label: 'Concluída', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
}

const ACTION_BADGE: Record<string, string> = {
  continue: 'border-green-200 bg-green-50 text-green-700',
  stop: 'border-red-200 bg-red-50 text-red-700',
  modify: 'border-yellow-200 bg-yellow-50 text-yellow-800',
  start: 'border-blue-200 bg-blue-50 text-blue-700',
}

function normalizeList(payload: ListResponse | Reconciliation[] | null | undefined): Reconciliation[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

function formatDateTime(value?: string | null) {
  if (!value) return null
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function ReconciliationList({ patientId }: { patientId: string }) {
  const [items, setItems] = useState<Reconciliation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    if (!patientId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse | Reconciliation[]>(
        `/api/v1/medication-reconciliations/?patient=${patientId}`
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

  if (loading) {
    return (
      <SectionState
        title="Carregando reconciliações..."
        detail="Buscando as reconciliações medicamentosas por transição."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar reconciliações"
        detail="Não foi possível carregar as reconciliações medicamentosas. Tente novamente."
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

  if (items.length === 0) {
    return (
      <SectionState
        title="Sem reconciliação medicamentosa"
        detail="Reconciliações por admissão, transferência ou alta aparecerão aqui com as decisões por medicamento."
      />
    )
  }

  return (
    <div className="space-y-3">
      {items.map((rec) => {
        const meta = STATUS_META[rec.status] ?? {
          label: rec.status_display ?? rec.status,
          badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
        }
        const when = formatDateTime(rec.completed_at ?? rec.created_at)
        return (
          <div key={rec.id} className="rounded-lg border border-slate-200 bg-white">
            <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <ClipboardCheck size={15} className="shrink-0 text-blue-600" />
                  <p className="text-sm font-semibold text-slate-900">
                    Reconciliação — {rec.moment_display ?? rec.moment}
                  </p>
                </div>
                {when && <p className="mt-1 text-xs text-slate-500">{when}</p>}
              </div>
              <StatusBadge meta={meta} />
            </div>
            <div className="divide-y divide-slate-100">
              {(rec.items ?? []).length === 0 ? (
                <p className="px-4 py-3 text-xs text-slate-500">Sem decisões registradas.</p>
              ) : (
                rec.items?.map((item) => (
                  <div key={item.id} className="flex items-start justify-between gap-3 px-4 py-2.5">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900">{item.medication_name}</p>
                      {item.home_dosage && (
                        <p className="mt-0.5 text-xs text-slate-500">Uso em casa: {item.home_dosage}</p>
                      )}
                      {item.reason && <p className="mt-0.5 text-xs text-slate-500">{item.reason}</p>}
                    </div>
                    <span
                      className={`shrink-0 inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${
                        ACTION_BADGE[item.action] ?? 'border-slate-200 bg-slate-50 text-slate-600'
                      }`}
                    >
                      {item.action_display ?? item.action}
                    </span>
                  </div>
                ))
              )}
            </div>
            {rec.notes && <p className="px-4 py-3 text-sm text-slate-600">{rec.notes}</p>}
          </div>
        )
      })}
    </div>
  )
}
