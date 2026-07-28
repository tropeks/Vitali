'use client'

import { useCallback, useEffect, useState } from 'react'
import { NotebookPen, RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import type { SaeListResponse } from './types'
import { formatSaeDateTime, normalizeSaeList } from './types'

/**
 * SAE — evolução de enfermagem (N4). Reads
 * GET /api/v1/nursing-evolutions/?patient=<id> (sae.read). Creating requires
 * sae.write AND an open encounter — the add control stays hidden otherwise
 * (the backend enforces 403 regardless).
 */

interface Evolution {
  id: string
  encounter?: string | null
  text: string
  created_by?: string | null
  created_at?: string | null
}

interface Props {
  patientId: string
  encounterId?: string | null
  canWrite: boolean
}

export default function SaeEvolution({ patientId, encounterId, canWrite }: Props) {
  const [items, setItems] = useState<Evolution[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const load = useCallback(async () => {
    if (!patientId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<SaeListResponse<Evolution> | Evolution[]>(
        `/api/v1/nursing-evolutions/?patient=${patientId}`
      )
      setItems(normalizeSaeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId])

  useEffect(() => {
    load()
  }, [load])

  const submit = async () => {
    if (!encounterId) {
      setSaveError('É necessário um atendimento aberto para registrar a evolução.')
      return
    }
    if (!text.trim()) {
      setSaveError('Descreva a evolução de enfermagem.')
      return
    }
    setSaving(true)
    setSaveError('')
    try {
      await apiFetch('/api/v1/nursing-evolutions/', {
        method: 'POST',
        body: JSON.stringify({ encounter: encounterId, text: text.trim() }),
      })
      setAdding(false)
      setText('')
      await load()
    } catch {
      setSaveError('Não foi possível salvar a evolução. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <SectionState title="Carregando evoluções..." detail="Buscando as evoluções de enfermagem." />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar evoluções"
        detail="Não foi possível carregar as evoluções de enfermagem. Tente novamente."
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
    <div className="space-y-3">
      {canWrite && !adding && (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
        >
          <NotebookPen size={15} />
          Adicionar evolução
        </button>
      )}

      {canWrite && adding && (
        <div className="rounded-lg border border-slate-200 bg-neu-panel p-4">
          <p className="text-sm font-semibold text-slate-900">Nova evolução de enfermagem</p>
          {!encounterId && (
            <p className="mt-1 text-xs text-yellow-800">
              Sem atendimento aberto — abra um atendimento para registrar a evolução.
            </p>
          )}
          <label className="mt-2 block text-xs font-semibold text-slate-600">
            Evolução
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={4}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
          {saveError && <p className="mt-2 text-xs font-semibold text-red-700">{saveError}</p>}
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? 'Salvando...' : 'Salvar evolução'}
            </button>
            <button
              type="button"
              onClick={() => {
                setAdding(false)
                setText('')
                setSaveError('')
              }}
              className="text-sm font-semibold text-slate-500 hover:underline"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <SectionState
          title="Sem evolução de enfermagem"
          detail="As evoluções de enfermagem do paciente aparecerão aqui em ordem cronológica."
        />
      ) : (
        items.map((evolution) => {
          const when = formatSaeDateTime(evolution.created_at)
          return (
            <div key={evolution.id} className="rounded-lg border border-slate-200 bg-white px-4 py-3">
              <div className="flex items-center gap-2">
                <NotebookPen size={14} className="shrink-0 text-blue-600" />
                {when && <span className="text-xs font-semibold text-slate-500">{when}</span>}
              </div>
              <p className="mt-2 whitespace-pre-line text-sm text-slate-700">{evolution.text}</p>
            </div>
          )
        })
      )}
    </div>
  )
}
