'use client'

import { useCallback, useEffect, useState } from 'react'
import { Stethoscope, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { StatusBadge } from '@/components/shared'
import {
  acuityMeta,
  normalizeList,
  type ListResponse,
  type ManchesterDiscriminatorOption,
  type ManchesterFlowchartOption,
} from './emergency-chart-types'

interface Props {
  boletimId: string
  onClose: () => void
  /** Called after a successful classify so the detail can refresh (append). */
  onClassified: () => void
}

/**
 * Reclassificar (emergency.classify) — a Manchester triagem: pick a fluxograma
 * (`/manchester-flowcharts/?q=`), then a discriminador
 * (`/manchester-discriminators/?flowchart=`), and POST
 * `/emergency-encounters/{id}/classify/` `{discriminator, notes?}`. Every call
 * appends a NEW RiskClassification (re-triagem never edits). The acuity/target
 * are copied server-side from the chosen discriminador.
 */
export default function EmergencyReclassifyModal({ boletimId, onClose, onClassified }: Props) {
  const [flowcharts, setFlowcharts] = useState<ManchesterFlowchartOption[]>([])
  const [flowchartsLoading, setFlowchartsLoading] = useState(true)
  const [flowchartId, setFlowchartId] = useState('')

  const [discriminators, setDiscriminators] = useState<ManchesterDiscriminatorOption[]>([])
  const [discriminatorsLoading, setDiscriminatorsLoading] = useState(false)
  const [discriminatorId, setDiscriminatorId] = useState('')

  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const loadFlowcharts = useCallback(async () => {
    setFlowchartsLoading(true)
    try {
      const data = await apiFetch<ListResponse<ManchesterFlowchartOption> | ManchesterFlowchartOption[]>(
        '/api/v1/manchester-flowcharts/',
      )
      setFlowcharts(normalizeList(data))
    } catch {
      setFlowcharts([])
    } finally {
      setFlowchartsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadFlowcharts()
  }, [loadFlowcharts])

  const selectFlowchart = useCallback(async (id: string) => {
    setFlowchartId(id)
    setDiscriminatorId('')
    setDiscriminators([])
    if (!id) return
    setDiscriminatorsLoading(true)
    try {
      const data = await apiFetch<
        ListResponse<ManchesterDiscriminatorOption> | ManchesterDiscriminatorOption[]
      >(`/api/v1/manchester-discriminators/?flowchart=${id}`)
      setDiscriminators(normalizeList(data))
    } catch {
      setDiscriminators([])
    } finally {
      setDiscriminatorsLoading(false)
    }
  }, [])

  const selected = discriminators.find((item) => item.id === discriminatorId) ?? null

  const submit = async () => {
    if (!discriminatorId) {
      setError('Selecione um fluxograma e um discriminador.')
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
        setError('Não foi possível classificar: transição inválida para este boletim.')
      } else {
        setError('Não foi possível registrar a classificação. Revise os dados e tente novamente.')
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
      aria-label="Reclassificar (triagem Manchester)"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <Stethoscope size={18} className="text-blue-600" />
            <h2 className="text-base font-semibold text-slate-900">Reclassificar (Manchester)</h2>
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
          <label className="block text-xs font-semibold text-slate-600">
            Fluxograma de apresentação
            <select
              aria-label="Fluxograma"
              value={flowchartId}
              onChange={(event) => selectFlowchart(event.target.value)}
              disabled={flowchartsLoading}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:opacity-60"
            >
              <option value="">
                {flowchartsLoading ? 'Carregando fluxogramas...' : 'Selecione um fluxograma'}
              </option>
              {flowcharts.map((flowchart) => (
                <option key={flowchart.id} value={flowchart.id}>
                  {flowchart.code} — {flowchart.display}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-semibold text-slate-600">
            Discriminador
            <select
              aria-label="Discriminador"
              value={discriminatorId}
              onChange={(event) => setDiscriminatorId(event.target.value)}
              disabled={!flowchartId || discriminatorsLoading}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:opacity-60"
            >
              <option value="">
                {!flowchartId
                  ? 'Selecione um fluxograma primeiro'
                  : discriminatorsLoading
                    ? 'Carregando discriminadores...'
                    : discriminators.length === 0
                      ? 'Nenhum discriminador'
                      : 'Selecione um discriminador'}
              </option>
              {discriminators.map((discriminator) => (
                <option key={discriminator.id} value={discriminator.id}>
                  {discriminator.code} — {discriminator.name}
                </option>
              ))}
            </select>
          </label>

          {selected && (
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="text-xs font-semibold text-slate-500">Acuidade resultante:</span>
              <StatusBadge meta={acuityMeta(selected.acuity_level)} />
              <span className="text-xs text-slate-500">
                Tempo-alvo {selected.target_minutes} min
              </span>
            </div>
          )}

          <label className="block text-xs font-semibold text-slate-600">
            Observações (opcional)
            <textarea
              aria-label="Observações"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              placeholder="Notas da triagem..."
            />
          </label>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? 'Classificando...' : 'Registrar classificação'}
          </button>
        </div>
      </div>
    </div>
  )
}
