'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Syringe } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'

/**
 * Governed patient immunization history (FHIR Immunization-style).
 * Backend: emr.Immunization via GET /api/v1/immunizations/?patient=<id>
 * (emr module, emr.read).
 */

interface Immunization {
  id: string
  immunobiological: string
  dose_number?: string | null
  lot?: string | null
  manufacturer?: string | null
  date: string
  pni_calendar_reference?: string | null
  notes?: string | null
}

interface ListResponse {
  results?: Immunization[]
  count?: number
}

function normalizeList(payload: ListResponse | Immunization[] | null | undefined): Immunization[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

function formatDate(value?: string | null) {
  if (!value) return 'Data não informada'
  return new Date(`${value}T00:00:00`).toLocaleDateString('pt-BR')
}

export default function ImmunizationList({ patientId }: { patientId: string }) {
  const [items, setItems] = useState<Immunization[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    if (!patientId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse | Immunization[]>(
        `/api/v1/immunizations/?patient=${patientId}`
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
    return <SectionState title="Carregando imunizações..." detail="Buscando o registro vacinal." />
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar imunizações"
        detail="Não foi possível carregar o registro vacinal. Tente novamente."
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
        title="Sem registro vacinal"
        detail="Doses aplicadas (vacina, data, lote e referência PNI) aparecerão aqui."
        tone="success"
      />
    )
  }

  return (
    <div className="space-y-2">
      {items.map((shot) => (
        <div key={shot.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Syringe size={15} className="shrink-0 text-blue-600" />
                <p className="text-sm font-semibold text-slate-900">{shot.immunobiological}</p>
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                {shot.dose_number && (
                  <span className="inline-flex rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                    {shot.dose_number}
                  </span>
                )}
                {shot.pni_calendar_reference && <span>{shot.pni_calendar_reference}</span>}
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-slate-700">{formatDate(shot.date)}</span>
          </div>
          {(shot.lot || shot.manufacturer) && (
            <p className="mt-2 text-xs text-slate-500">
              {shot.lot && `Lote ${shot.lot}`}
              {shot.lot && shot.manufacturer && ' | '}
              {shot.manufacturer}
            </p>
          )}
          {shot.notes && <p className="mt-2 text-sm text-slate-600">{shot.notes}</p>}
        </div>
      ))}
    </div>
  )
}
