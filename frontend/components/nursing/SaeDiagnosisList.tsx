'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw, Stethoscope } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import SaeCareplan from './SaeCareplan'
import type { NandaOption, SaeListResponse } from './types'
import { normalizeSaeList } from './types'

/**
 * SAE — nursing-diagnosis list (N4). Surfaces the executable SAE domain (N2)
 * on the patient chart. Reads GET /api/v1/nursing-diagnoses/?patient=<id>
 * (sae.read); creating requires sae.write AND an open encounter (the add
 * controls stay hidden otherwise — the backend enforces 403 regardless).
 *
 * The NANDA picker (terminology autocomplete) exposes only a `code`/`display`
 * pair (no catalog PK), so a new diagnosis is posted with `nanda_code`.
 */

interface NursingDiagnosis {
  id: string
  encounter?: string | null
  nanda?: number | null
  nanda_code?: string | null
  legacy_nanda_text?: string | null
  nanda_unmatched?: boolean | null
  related_factors?: string | null
  defining_characteristics?: string | null
  status: string
  priority?: string | null
  created_at?: string | null
}

const STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  active: { label: 'Ativo', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
  resolved: { label: 'Resolvido', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
}

const PRIORITY_META: Record<string, { label: string; badgeClass: string }> = {
  high: { label: 'Alta', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
  medium: { label: 'Média', badgeClass: 'border-yellow-200 bg-yellow-50 text-yellow-800' },
  low: { label: 'Baixa', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
}

const STATUS_ORDER: Record<string, number> = { active: 0, resolved: 1 }

function diagnosisLabel(diagnosis: NursingDiagnosis): string {
  if (diagnosis.legacy_nanda_text) return diagnosis.legacy_nanda_text
  if (diagnosis.nanda_code) return `Diagnóstico NANDA ${diagnosis.nanda_code}`
  return 'Diagnóstico de enfermagem'
}

interface Props {
  patientId: string
  encounterId?: string | null
  canWrite: boolean
}

export default function SaeDiagnosisList({ patientId, encounterId, canWrite }: Props) {
  const [items, setItems] = useState<NursingDiagnosis[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const [adding, setAdding] = useState(false)
  const [nanda, setNanda] = useState<NandaOption | null>(null)
  const [status, setStatus] = useState('active')
  const [priority, setPriority] = useState('medium')
  const [relatedFactors, setRelatedFactors] = useState('')
  const [definingCharacteristics, setDefiningCharacteristics] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const load = useCallback(async () => {
    if (!patientId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<SaeListResponse<NursingDiagnosis> | NursingDiagnosis[]>(
        `/api/v1/nursing-diagnoses/?patient=${patientId}`
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

  const sorted = useMemo(
    () =>
      [...items].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)),
    [items]
  )

  const resetForm = () => {
    setNanda(null)
    setStatus('active')
    setPriority('medium')
    setRelatedFactors('')
    setDefiningCharacteristics('')
    setSaveError('')
  }

  const submit = async () => {
    if (!encounterId) {
      setSaveError('É necessário um atendimento aberto para registrar o diagnóstico.')
      return
    }
    setSaving(true)
    setSaveError('')
    const payload: Record<string, unknown> = { encounter: encounterId, status, priority }
    if (nanda?.code) payload.nanda_code = nanda.code
    if (relatedFactors.trim()) payload.related_factors = relatedFactors.trim()
    if (definingCharacteristics.trim())
      payload.defining_characteristics = definingCharacteristics.trim()
    try {
      await apiFetch('/api/v1/nursing-diagnoses/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setAdding(false)
      resetForm()
      await load()
    } catch {
      setSaveError('Não foi possível salvar o diagnóstico. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando diagnósticos..."
        detail="Buscando os diagnósticos de enfermagem (SAE)."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar diagnósticos"
        detail="Não foi possível carregar os diagnósticos de enfermagem. Tente novamente."
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
          <Stethoscope size={15} />
          Adicionar diagnóstico
        </button>
      )}

      {canWrite && adding && (
        <div className="rounded-lg border border-slate-200 bg-neu-panel p-4">
          <p className="text-sm font-semibold text-slate-900">Novo diagnóstico de enfermagem</p>
          {!encounterId && (
            <p className="mt-1 text-xs text-yellow-800">
              Sem atendimento aberto — abra um atendimento para registrar o diagnóstico.
            </p>
          )}
          <div className="mt-3 space-y-3">
            <RemoteCombobox<NandaOption>
              label="NANDA (diagnóstico)"
              endpoint="/api/v1/terminology/nanda/"
              queryParam="q"
              value={nanda}
              getKey={(item) => item.code}
              getLabel={(item) => `${item.code} — ${item.display}`}
              onChange={setNanda}
              placeholder="Buscar diagnóstico NANDA..."
            />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="text-xs font-semibold text-slate-600">
                Status
                <select
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                >
                  <option value="active">Ativo</option>
                  <option value="resolved">Resolvido</option>
                </select>
              </label>
              <label className="text-xs font-semibold text-slate-600">
                Prioridade
                <select
                  value={priority}
                  onChange={(event) => setPriority(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                >
                  <option value="high">Alta</option>
                  <option value="medium">Média</option>
                  <option value="low">Baixa</option>
                </select>
              </label>
            </div>
            <label className="block text-xs font-semibold text-slate-600">
              Fatores relacionados
              <input
                value={relatedFactors}
                onChange={(event) => setRelatedFactors(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs font-semibold text-slate-600">
              Características definidoras
              <input
                value={definingCharacteristics}
                onChange={(event) => setDefiningCharacteristics(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            {saveError && <p className="text-xs font-semibold text-red-700">{saveError}</p>}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={submit}
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {saving ? 'Salvando...' : 'Salvar diagnóstico'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setAdding(false)
                  resetForm()
                }}
                className="text-sm font-semibold text-slate-500 hover:underline"
              >
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}

      {sorted.length === 0 ? (
        <SectionState
          title="Sem diagnósticos de enfermagem"
          detail="Diagnósticos NANDA, plano de cuidados (NOC/NIC) e prescrição de enfermagem aparecerão aqui."
        />
      ) : (
        sorted.map((diagnosis) => {
          const meta = STATUS_META[diagnosis.status] ?? {
            label: diagnosis.status,
            badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
          }
          const priorityMeta = diagnosis.priority ? PRIORITY_META[diagnosis.priority] : null
          const isOpen = !!expanded[diagnosis.id]
          return (
            <div key={diagnosis.id} className="rounded-lg border border-slate-200 bg-white">
              <button
                type="button"
                onClick={() =>
                  setExpanded((current) => ({ ...current, [diagnosis.id]: !current[diagnosis.id] }))
                }
                aria-expanded={isOpen}
                className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left"
              >
                <div className="flex min-w-0 items-start gap-2">
                  {isOpen ? (
                    <ChevronDown size={16} className="mt-0.5 shrink-0 text-slate-400" />
                  ) : (
                    <ChevronRight size={16} className="mt-0.5 shrink-0 text-slate-400" />
                  )}
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-900">
                      {diagnosisLabel(diagnosis)}
                    </p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                      <span className="font-mono">
                        {diagnosis.nanda_code ? `NANDA ${diagnosis.nanda_code}` : 'Sem NANDA'}
                      </span>
                      {diagnosis.nanda_unmatched && (
                        <span className="inline-flex rounded-full border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-[11px] font-semibold text-yellow-800">
                          não reconciliado
                        </span>
                      )}
                      {priorityMeta && <span>| Prioridade {priorityMeta.label}</span>}
                    </p>
                  </div>
                </div>
                <StatusBadge meta={meta} />
              </button>
              {(diagnosis.related_factors || diagnosis.defining_characteristics) && (
                <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
                  {diagnosis.related_factors && (
                    <p>Fatores relacionados: {diagnosis.related_factors}</p>
                  )}
                  {diagnosis.defining_characteristics && (
                    <p className="mt-0.5">
                      Características definidoras: {diagnosis.defining_characteristics}
                    </p>
                  )}
                </div>
              )}
              {isOpen && (
                <div className="border-t border-slate-100 bg-neu-panel px-4 py-3">
                  <SaeCareplan diagnosisId={diagnosis.id} canWrite={canWrite} />
                </div>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}
