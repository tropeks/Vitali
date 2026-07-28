'use client'

import { useEffect, useMemo, useState } from 'react'
import { Stethoscope, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  acuityMeta,
  formatWaited,
  normalizeList,
  type DiscriminatorOption,
  type FlowchartOption,
  type ListResponse,
} from './ps-board-types'

interface TriageClassifyModalProps {
  boletimId: string
  patientName: string
  onClose: () => void
  /** Called after a successful classificação so the board can refetch. */
  onClassified: () => void
}

/**
 * Classificar (triagem Manchester, emergency.classify) — picks a fluxograma
 * (`/manchester-flowcharts/?q=`) then a discriminador (`/manchester-discriminators/
 * ?flowchart=<pk>`), showing the acuidade + tempo-alvo the discriminador dispara,
 * and posts POST /emergency-encounters/{id}/classify/ {discriminator, notes?}.
 * A re-triagem is a new call (backend appends; never edits).
 */
export default function TriageClassifyModal({
  boletimId,
  patientName,
  onClose,
  onClassified,
}: TriageClassifyModalProps) {
  const [flowchart, setFlowchart] = useState<FlowchartOption | null>(null)
  const [discriminators, setDiscriminators] = useState<DiscriminatorOption[]>([])
  const [discriminatorsLoading, setDiscriminatorsLoading] = useState(false)
  const [discriminatorId, setDiscriminatorId] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setDiscriminatorId('')
    if (!flowchart) {
      setDiscriminators([])
      return
    }
    let active = true
    setDiscriminatorsLoading(true)
    apiFetch<ListResponse<DiscriminatorOption> | DiscriminatorOption[]>(
      `/api/v1/manchester-discriminators/?flowchart=${encodeURIComponent(flowchart.id)}`,
    )
      .then((data) => {
        if (active) setDiscriminators(normalizeList(data))
      })
      .catch(() => {
        if (active) setDiscriminators([])
      })
      .finally(() => {
        if (active) setDiscriminatorsLoading(false)
      })
    return () => {
      active = false
    }
  }, [flowchart])

  const selected = useMemo(
    () => discriminators.find((d) => d.id === discriminatorId) ?? null,
    [discriminators, discriminatorId],
  )
  const selectedMeta = selected ? acuityMeta(selected.acuity_level) : null

  async function submit() {
    if (!discriminatorId) {
      setError('Selecione um discriminador para classificar.')
      return
    }
    setSaving(true)
    setError('')
    const body: Record<string, string> = { discriminator: discriminatorId }
    if (notes.trim()) body.notes = notes.trim()
    try {
      await apiFetch(`/api/v1/emergency-encounters/${boletimId}/classify/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onClassified()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Não foi possível classificar este boletim na situação atual.')
      } else {
        setError('Não foi possível classificar. Tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Classificar risco"
    >
      <div className="w-full max-w-lg rounded-xl border border-white bg-neu-panel shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <Stethoscope size={18} className="text-neu-brand" aria-hidden />
            <div>
              <h2 className="text-base font-semibold text-neu-ink">Classificar risco</h2>
              <p className="text-xs text-neu-inkMuted">{patientName}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div>
            <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">Fluxograma</span>
            <RemoteCombobox<FlowchartOption>
              label="Fluxograma"
              endpoint="/api/v1/manchester-flowcharts/"
              queryParam="q"
              value={flowchart}
              getKey={(item) => item.id}
              getLabel={(item) => `${item.code} — ${item.display}`}
              onChange={setFlowchart}
              placeholder="Buscar fluxograma..."
            />
          </div>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Discriminador
            <select
              aria-label="Discriminador"
              value={discriminatorId}
              onChange={(e) => setDiscriminatorId(e.target.value)}
              disabled={!flowchart || discriminatorsLoading}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink disabled:opacity-60"
            >
              <option value="">
                {!flowchart
                  ? 'Selecione um fluxograma primeiro'
                  : discriminatorsLoading
                    ? 'Carregando discriminadores...'
                    : discriminators.length === 0
                      ? 'Nenhum discriminador'
                      : 'Selecione um discriminador'}
              </option>
              {discriminators.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({acuityMeta(d.acuity_level).label})
                </option>
              ))}
            </select>
          </label>

          {selected && selectedMeta && (
            <div
              className={`flex items-center justify-between rounded-lg border px-3 py-2 ${selectedMeta.rowClass}`}
            >
              <span
                className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${selectedMeta.badgeClass}`}
              >
                {selectedMeta.fullLabel}
              </span>
              <span className="text-xs font-semibold">
                Tempo-alvo: {formatWaited(selected.target_minutes)}
              </span>
            </div>
          )}

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Observações (opcional)
            <textarea
              aria-label="Observações"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink"
              placeholder="Notas da triagem..."
            />
          </label>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-neu-inkSoft hover:bg-neu-panel"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Classificando...' : 'Classificar'}
          </button>
        </div>
      </div>
    </div>
  )
}
