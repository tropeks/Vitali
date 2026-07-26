'use client'

import { useCallback, useEffect, useState } from 'react'
import { Clock, RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import type { SaeListResponse } from './types'
import { formatSaeDateTime, normalizeSaeList } from './types'

/**
 * SAE — prescrição de enfermagem for an intervention (N4). Reads
 * GET /api/v1/nursing-prescription-items/?intervention=<id>. These items are
 * executable — a frequency (h) + start drive the aprazamento/checagem (N5 owns
 * the MAR). Creating requires sae.write; `frequency_hours` must be > 0.
 */

interface PrescriptionItem {
  id: string
  intervention?: string | null
  description?: string | null
  frequency_hours?: number | null
  start_at?: string | null
  active?: boolean | null
}

const ACTIVE_META = { label: 'Ativa', badgeClass: 'border-green-200 bg-green-50 text-green-700' }
const INACTIVE_META = { label: 'Inativa', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' }

interface Props {
  interventionId: string
  canWrite: boolean
}

export default function SaePrescription({ interventionId, canWrite }: Props) {
  const [items, setItems] = useState<PrescriptionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [adding, setAdding] = useState(false)
  const [description, setDescription] = useState('')
  const [frequency, setFrequency] = useState('')
  const [startAt, setStartAt] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const load = useCallback(async () => {
    if (!interventionId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<SaeListResponse<PrescriptionItem> | PrescriptionItem[]>(
        `/api/v1/nursing-prescription-items/?intervention=${interventionId}`
      )
      setItems(normalizeSaeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [interventionId])

  useEffect(() => {
    load()
  }, [load])

  const submit = async () => {
    const hours = Number.parseInt(frequency, 10)
    if (!Number.isFinite(hours) || hours <= 0) {
      setSaveError('Informe uma frequência em horas maior que zero.')
      return
    }
    if (!startAt) {
      setSaveError('Informe o início da prescrição.')
      return
    }
    setSaving(true)
    setSaveError('')
    const payload = {
      intervention: interventionId,
      description: description.trim(),
      frequency_hours: hours,
      start_at: new Date(startAt).toISOString(),
      active: true,
    }
    try {
      await apiFetch('/api/v1/nursing-prescription-items/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setAdding(false)
      setDescription('')
      setFrequency('')
      setStartAt('')
      await load()
    } catch {
      setSaveError('Não foi possível salvar a prescrição. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando prescrição..."
        detail="Buscando os itens executáveis da prescrição de enfermagem."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar prescrição"
        detail="Não foi possível carregar a prescrição de enfermagem. Tente novamente."
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

  return (
    <div className="space-y-2">
      {items.length === 0 ? (
        <SectionState
          title="Sem prescrição de enfermagem"
          detail="Itens executáveis (descrição + frequência) para esta intervenção aparecerão aqui."
        />
      ) : (
        items.map((item) => {
          const when = formatSaeDateTime(item.start_at)
          return (
            <div key={item.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">
                    {item.description || 'Item de prescrição'}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <Clock size={12} />
                      {item.frequency_hours
                        ? `De ${item.frequency_hours} em ${item.frequency_hours} h`
                        : 'Frequência não definida'}
                    </span>
                    {when && <span>| Início {when}</span>}
                  </p>
                </div>
                <StatusBadge meta={item.active === false ? INACTIVE_META : ACTIVE_META} />
              </div>
            </div>
          )
        })
      )}

      {canWrite && !adding && (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="text-xs font-semibold text-blue-700 hover:underline"
        >
          + Adicionar prescrição
        </button>
      )}

      {canWrite && adding && (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <label className="block text-xs font-semibold text-slate-600">
            Descrição
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="block text-xs font-semibold text-slate-600">
              Frequência (horas)
              <input
                type="number"
                min={1}
                value={frequency}
                onChange={(event) => setFrequency(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs font-semibold text-slate-600">
              Início
              <input
                type="datetime-local"
                value={startAt}
                onChange={(event) => setStartAt(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>
          {saveError && <p className="mt-2 text-xs font-semibold text-red-700">{saveError}</p>}
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? 'Salvando...' : 'Salvar prescrição'}
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="text-xs font-semibold text-slate-500 hover:underline"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
