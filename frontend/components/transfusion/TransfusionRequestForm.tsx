'use client'

import { useEffect, useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  URGENCIA_OPTIONS,
  normalizeList,
  type BloodComponentOption,
  type ListResponse,
  type TransfusionRequest,
  type TransfusionRequestPayload,
  type Urgencia,
} from './transfusion-types'

interface TransfusionRequestFormProps {
  patientId: string
  /** Active order parent — the requisição ties to the patient's open encounter. */
  encounterId: string | null
  onClose: () => void
  onCreated: (request: TransfusionRequest) => void
}

/**
 * Nova requisição transfusional (H6). Picks a hemocomponente from the H1 catalog
 * (`GET /api/v1/blood-components/`), the quantidade, urgência, indicação clínica
 * and (optional) CID, and POSTs `/api/v1/transfusion-requests/` tied to the
 * patient's active encounter (the required order parent). Field-level backend
 * validation errors (400) are surfaced inline.
 */
export default function TransfusionRequestForm({
  patientId,
  encounterId,
  onClose,
  onCreated,
}: TransfusionRequestFormProps) {
  const [components, setComponents] = useState<BloodComponentOption[]>([])
  const [component, setComponent] = useState('')
  const [quantidade, setQuantidade] = useState('1')
  const [urgencia, setUrgencia] = useState<Urgencia>('rotina')
  const [indicacao, setIndicacao] = useState('')
  const [cid, setCid] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let alive = true
    apiFetch<ListResponse<BloodComponentOption> | BloodComponentOption[]>(
      '/api/v1/blood-components/',
    )
      .then((data) => {
        if (alive) setComponents(normalizeList(data))
      })
      .catch(() => {
        /* catalog optional — the field still accepts a typed pk */
      })
    return () => {
      alive = false
    }
  }, [])

  function firstError(payload: unknown, field: string): string | undefined {
    if (payload && typeof payload === 'object') {
      const value = (payload as Record<string, unknown>)[field]
      if (Array.isArray(value) && value.length > 0) return String(value[0])
      if (typeof value === 'string') return value
    }
    return undefined
  }

  async function submit() {
    setSubmitting(true)
    setError(null)
    setFieldErrors({})
    const body: TransfusionRequestPayload = {
      patient: patientId,
      component: Number(component),
      quantidade: Number(quantidade),
      urgencia,
      indicacao: indicacao.trim(),
    }
    if (encounterId) body.encounter = encounterId
    if (cid.trim()) body.cid = cid.trim()
    try {
      const created = await apiFetch<TransfusionRequest>('/api/v1/transfusion-requests/', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onCreated(created)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const next: Record<string, string> = {}
        for (const field of ['component', 'quantidade', 'indicacao', 'urgencia', 'cid', 'encounter']) {
          const message = firstError(err.body, field)
          if (message) next[field] = message
        }
        const nonField = firstError(err.body, 'detail') ?? firstError(err.body, 'non_field_errors')
        if (nonField) setError(nonField)
        setFieldErrors(next)
        return
      }
      setError('Erro ao criar a requisição. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit =
    component.trim() !== '' && Number(quantidade) > 0 && indicacao.trim() !== '' && !submitting

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Nova requisição transfusional"
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Nova requisição transfusional</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Solicitação de hemocomponente vinculada ao atendimento ativo do paciente.
          </p>
        </div>

        {!encounterId && (
          <p className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
            Sem consulta/internação aberta: a requisição precisa de um atendimento ativo como
            vínculo. Abra ou selecione um atendimento antes de solicitar.
          </p>
        )}

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Hemocomponente</span>
            <select
              aria-label="Hemocomponente"
              value={component}
              onChange={(e) => setComponent(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            >
              <option value="">Selecione…</option>
              {components.map((option) => (
                <option key={option.id} value={String(option.id)}>
                  {option.display} ({option.code})
                </option>
              ))}
            </select>
            {fieldErrors.component && (
              <span className="mt-1 block text-xs text-red-700">{fieldErrors.component}</span>
            )}
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-neu-ink">Quantidade</span>
              <input
                aria-label="Quantidade"
                type="number"
                min={1}
                value={quantidade}
                onChange={(e) => setQuantidade(e.target.value)}
                className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              />
              {fieldErrors.quantidade && (
                <span className="mt-1 block text-xs text-red-700">{fieldErrors.quantidade}</span>
              )}
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-neu-ink">Urgência</span>
              <select
                aria-label="Urgência"
                value={urgencia}
                onChange={(e) => setUrgencia(e.target.value as Urgencia)}
                className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              >
                {URGENCIA_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {fieldErrors.urgencia && (
                <span className="mt-1 block text-xs text-red-700">{fieldErrors.urgencia}</span>
              )}
            </label>
          </div>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Indicação clínica</span>
            <textarea
              aria-label="Indicação clínica"
              value={indicacao}
              onChange={(e) => setIndicacao(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              placeholder="Indicação clínica da transfusão (ex.: anemia sintomática, Hb < 7)."
            />
            {fieldErrors.indicacao && (
              <span className="mt-1 block text-xs text-red-700">{fieldErrors.indicacao}</span>
            )}
          </label>

          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">CID (opcional)</span>
            <input
              aria-label="CID"
              value={cid}
              onChange={(e) => setCid(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              autoComplete="off"
              placeholder="Ex.: D64.9"
            />
            {fieldErrors.cid && (
              <span className="mt-1 block text-xs text-red-700">{fieldErrors.cid}</span>
            )}
          </label>
          {fieldErrors.encounter && (
            <p className="text-xs text-red-700">{fieldErrors.encounter}</p>
          )}
        </div>

        {error && <p className="text-sm text-red-700">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-panel"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            Solicitar
          </button>
        </div>
      </div>
    </div>
  )
}
