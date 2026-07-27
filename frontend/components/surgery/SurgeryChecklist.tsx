'use client'

import { useState } from 'react'
import { CheckCircle2, ListChecks } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  CHECKLIST_PHASES,
  formatDateTime,
  type SurgicalChecklistEntry,
} from './surgery-case-types'

interface Props {
  caseId: string
  /** Already-confirmed phases of the case (from the timeline). */
  confirmed: SurgicalChecklistEntry[]
  /** `surgery.manage` — gates the confirm forms. */
  canManage: boolean
  /** Called after a successful confirm so the panel can reload the timeline. */
  onConfirmed: () => void
}

/**
 * Checklist de cirurgia segura (OMS) — the 3 WHO phases (sign in / time out /
 * sign out). A confirmed phase renders as done; an unconfirmed one shows a small
 * item-confirm form gated by `surgery.manage`
 * (`POST /surgical-cases/{id}/checklist/`). A phase confirmed concurrently → 409,
 * treated as "already confirmed" (the panel reloads to show it done).
 */
export default function SurgeryChecklist({ caseId, confirmed, canManage, onConfirmed }: Props) {
  const confirmedByPhase = new Map(confirmed.map((entry) => [entry.phase, entry]))

  return (
    <div className="space-y-3" aria-label="Checklist de cirurgia segura">
      {CHECKLIST_PHASES.map((phase) => {
        const entry = confirmedByPhase.get(phase.value)
        if (entry) {
          return <ConfirmedPhase key={phase.value} label={phase.label} entry={entry} />
        }
        return (
          <PhaseForm
            key={phase.value}
            caseId={caseId}
            phase={phase}
            canManage={canManage}
            onConfirmed={onConfirmed}
          />
        )
      })}
    </div>
  )
}

function ConfirmedPhase({
  label,
  entry,
}: {
  label: string
  entry: SurgicalChecklistEntry
}) {
  const confirmedItems = Object.entries(entry.items ?? {}).filter(([, value]) => value)
  return (
    <section className="rounded-lg border border-green-200 bg-green-50 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 size={16} className="text-green-600" />
          <h4 className="text-sm font-semibold text-slate-900">{label}</h4>
        </div>
        <span className="text-xs font-semibold text-green-700">Fase confirmada</span>
      </div>
      <p className="mt-1 text-xs text-slate-600">
        {formatDateTime(entry.confirmed_at)} · {confirmedItems.length} item(ns) confirmado(s)
      </p>
    </section>
  )
}

function PhaseForm({
  caseId,
  phase,
  canManage,
  onConfirmed,
}: {
  caseId: string
  phase: { value: string; label: string; items: Array<{ key: string; label: string }> }
  canManage: boolean
  onConfirmed: () => void
}) {
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const toggle = (key: string) =>
    setChecked((current) => ({ ...current, [key]: !current[key] }))

  const submit = async () => {
    setSaving(true)
    setError('')
    const items = phase.items.reduce<Record<string, boolean>>((acc, item) => {
      acc[item.key] = Boolean(checked[item.key])
      return acc
    }, {})
    try {
      await apiFetch(`/api/v1/surgical-cases/${caseId}/checklist/`, {
        method: 'POST',
        body: JSON.stringify({ phase: phase.value, items }),
      })
      onConfirmed()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Phase confirmed elsewhere — reload so it renders as done.
        onConfirmed()
      } else {
        setError('Não foi possível confirmar a fase. Tente novamente.')
        setSaving(false)
      }
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2">
        <ListChecks size={16} className="text-slate-400" />
        <h4 className="text-sm font-semibold text-slate-900">{phase.label}</h4>
      </div>
      {canManage ? (
        <>
          <div className="mt-3 space-y-2">
            {phase.items.map((item) => (
              <label key={item.key} className="flex items-start gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={Boolean(checked[item.key])}
                  onChange={() => toggle(item.key)}
                  className="mt-0.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                {item.label}
              </label>
            ))}
          </div>
          {error && <p className="mt-2 text-xs font-semibold text-red-700">{error}</p>}
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? 'Confirmando...' : 'Confirmar fase'}
          </button>
        </>
      ) : (
        <p className="mt-2 text-xs text-slate-500">Fase pendente de confirmação.</p>
      )}
    </section>
  )
}
