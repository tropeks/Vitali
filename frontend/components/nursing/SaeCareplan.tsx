'use client'

import { useCallback, useEffect, useState } from 'react'
import { Activity, RefreshCw, Target } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import SaePrescription from './SaePrescription'
import type { NicOption, NocOption, SaeListResponse } from './types'
import { normalizeSaeList } from './types'

/**
 * SAE — plano de cuidados for a diagnosis (N4). Reads
 * GET /api/v1/nursing-careplans/?diagnosis=<id> (NOC resultado esperado + meta)
 * and, per careplan, GET /api/v1/nursing-care-interventions/?careplan=<id>
 * (NIC intervenções). Each intervention drives its executable prescription
 * (SaePrescription). Writes carry `noc_code`/`nic_code` from the pickers.
 */

interface Careplan {
  id: string
  diagnosis?: string | null
  noc?: number | null
  noc_code?: string | null
  noc_unmatched?: boolean | null
  expected_outcome?: string | null
  target?: string | null
}

interface Intervention {
  id: string
  careplan?: string | null
  nic?: number | null
  nic_code?: string | null
  nic_unmatched?: boolean | null
  notes?: string | null
}

interface Props {
  diagnosisId: string
  canWrite: boolean
}

export default function SaeCareplan({ diagnosisId, canWrite }: Props) {
  const [items, setItems] = useState<Careplan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [adding, setAdding] = useState(false)
  const [noc, setNoc] = useState<NocOption | null>(null)
  const [expectedOutcome, setExpectedOutcome] = useState('')
  const [target, setTarget] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  const load = useCallback(async () => {
    if (!diagnosisId) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<SaeListResponse<Careplan> | Careplan[]>(
        `/api/v1/nursing-careplans/?diagnosis=${diagnosisId}`
      )
      setItems(normalizeSaeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [diagnosisId])

  useEffect(() => {
    load()
  }, [load])

  const submit = async () => {
    setSaving(true)
    setSaveError('')
    const payload: Record<string, unknown> = { diagnosis: diagnosisId }
    if (noc?.code) payload.noc_code = noc.code
    if (expectedOutcome.trim()) payload.expected_outcome = expectedOutcome.trim()
    if (target.trim()) payload.target = target.trim()
    try {
      await apiFetch('/api/v1/nursing-careplans/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setAdding(false)
      setNoc(null)
      setExpectedOutcome('')
      setTarget('')
      await load()
    } catch {
      setSaveError('Não foi possível salvar o plano. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <SectionState title="Carregando plano..." detail="Buscando o plano de cuidados (NOC/NIC)." />
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar plano"
        detail="Não foi possível carregar o plano de cuidados. Tente novamente."
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
          className="text-xs font-semibold text-blue-700 hover:underline"
        >
          + Adicionar plano
        </button>
      )}

      {canWrite && adding && (
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <RemoteCombobox<NocOption>
            label="NOC (resultado esperado)"
            endpoint="/api/v1/terminology/noc/"
            queryParam="q"
            value={noc}
            getKey={(item) => item.code}
            getLabel={(item) => `${item.code} — ${item.display}`}
            onChange={setNoc}
            placeholder="Buscar resultado NOC..."
          />
          <label className="mt-2 block text-xs font-semibold text-slate-600">
            Resultado esperado
            <input
              value={expectedOutcome}
              onChange={(event) => setExpectedOutcome(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
          <label className="mt-2 block text-xs font-semibold text-slate-600">
            Meta
            <input
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>
          {saveError && <p className="mt-2 text-xs font-semibold text-red-700">{saveError}</p>}
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={saving}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? 'Salvando...' : 'Salvar plano'}
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

      {items.length === 0 ? (
        <SectionState
          title="Sem plano de cuidados"
          detail="Adicione um resultado esperado (NOC) e intervenções (NIC) para este diagnóstico."
        />
      ) : (
        items.map((careplan) => (
          <CareplanCard key={careplan.id} careplan={careplan} canWrite={canWrite} />
        ))
      )}
    </div>
  )
}

function CareplanCard({ careplan, canWrite }: { careplan: Careplan; canWrite: boolean }) {
  const [interventions, setInterventions] = useState<Intervention[]>([])

  const [adding, setAdding] = useState(false)
  const [nic, setNic] = useState<NicOption | null>(null)
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<SaeListResponse<Intervention> | Intervention[]>(
        `/api/v1/nursing-care-interventions/?careplan=${careplan.id}`
      )
      setInterventions(normalizeSaeList(data))
    } catch {
      setInterventions([])
    }
  }, [careplan.id])

  useEffect(() => {
    load()
  }, [load])

  const submit = async () => {
    setSaving(true)
    const payload: Record<string, unknown> = { careplan: careplan.id }
    if (nic?.code) payload.nic_code = nic.code
    if (notes.trim()) payload.notes = notes.trim()
    try {
      await apiFetch('/api/v1/nursing-care-interventions/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setAdding(false)
      setNic(null)
      setNotes('')
      await load()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-start gap-2">
        <Target size={15} className="mt-0.5 shrink-0 text-green-600" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900">
            {careplan.expected_outcome || 'Resultado esperado não descrito'}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
            <span className="font-mono">{careplan.noc_code ? `NOC ${careplan.noc_code}` : 'Sem NOC'}</span>
            {careplan.noc_unmatched && (
              <span className="inline-flex rounded-full border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-[11px] font-semibold text-yellow-800">
                não reconciliado
              </span>
            )}
          </p>
          {careplan.target && <p className="mt-1 text-xs text-slate-600">Meta: {careplan.target}</p>}
        </div>
      </div>

      <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Intervenções (NIC)</p>
        {interventions.length === 0 ? (
          <p className="text-xs text-slate-500">Sem intervenções registradas.</p>
        ) : (
          interventions.map((intervention) => (
            <div key={intervention.id} className="rounded-lg border border-slate-100 bg-neu-panel px-3 py-2">
              <div className="flex items-start gap-2">
                <Activity size={14} className="mt-0.5 shrink-0 text-blue-600" />
                <div className="min-w-0">
                  <p className="text-sm text-slate-800">{intervention.notes || 'Intervenção de enfermagem'}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                    <span className="font-mono">
                      {intervention.nic_code ? `NIC ${intervention.nic_code}` : 'Sem NIC'}
                    </span>
                    {intervention.nic_unmatched && (
                      <span className="inline-flex rounded-full border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-[11px] font-semibold text-yellow-800">
                        não reconciliado
                      </span>
                    )}
                  </p>
                </div>
              </div>
              <div className="mt-2">
                <SaePrescription interventionId={intervention.id} canWrite={canWrite} />
              </div>
            </div>
          ))
        )}

        {canWrite && !adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="text-xs font-semibold text-blue-700 hover:underline"
          >
            + Adicionar intervenção
          </button>
        )}

        {canWrite && adding && (
          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <RemoteCombobox<NicOption>
              label="NIC (intervenção)"
              endpoint="/api/v1/terminology/nic/"
              queryParam="q"
              value={nic}
              getKey={(item) => item.code}
              getLabel={(item) => `${item.code} — ${item.display}`}
              onChange={setNic}
              placeholder="Buscar intervenção NIC..."
            />
            <label className="mt-2 block text-xs font-semibold text-slate-600">
              Observações
              <input
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={submit}
                disabled={saving}
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {saving ? 'Salvando...' : 'Salvar intervenção'}
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
    </div>
  )
}
