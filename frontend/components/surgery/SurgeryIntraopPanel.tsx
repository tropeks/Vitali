'use client'

import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, Clock, ListChecks, RefreshCw, Users } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import SurgeryTimeline from './SurgeryTimeline'
import RecordTimeControl from './RecordTimeControl'
import SurgeryChecklist from './SurgeryChecklist'
import SurgeryTeamPanel from './SurgeryTeamPanel'
import { CASE_STATUS_META, type CaseTimeline } from './surgery-case-types'

interface Props {
  caseId: string
  /** `surgery.manage` — gates every write (record-time / checklist / team). */
  canManage: boolean
  /** Return to the case list. */
  onBack: () => void
}

const EMPTY_TIMELINE: CaseTimeline = {
  case: '',
  status: '',
  times: [],
  checklists: [],
  team: [],
}

/**
 * Intra-op panel (C5) — the surgical prontuário of a single case. Fetches
 * `GET /surgical-cases/{id}/timeline/` (gated `surgery.read`) and composes the
 * three intra-op surfaces: tempos cirúrgicos (+ gated Registrar tempo),
 * checklist OMS (3 phases) and equipe. The case status is shown prominently and
 * advances as times are recorded; every write is gated `surgery.manage` and
 * reloads the timeline.
 */
export default function SurgeryIntraopPanel({ caseId, canManage, onBack }: Props) {
  const [timeline, setTimeline] = useState<CaseTimeline>(EMPTY_TIMELINE)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<CaseTimeline>(`/api/v1/surgical-cases/${caseId}/timeline/`)
      setTimeline({
        case: data.case,
        status: data.status,
        times: data.times ?? [],
        checklists: data.checklists ?? [],
        team: data.team ?? [],
      })
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => {
    load()
  }, [load])

  const statusMeta = CASE_STATUS_META[timeline.status] ?? {
    label: timeline.status || 'Situação',
    badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900"
        >
          <ArrowLeft size={15} />
          Voltar aos casos
        </button>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline"
        >
          <RefreshCw size={13} />
          Atualizar
        </button>
      </div>

      {loading ? (
        <SectionState
          title="Carregando prontuário cirúrgico..."
          detail="Buscando tempos, checklist e equipe do caso."
        />
      ) : error ? (
        <SectionState
          title="Erro ao carregar prontuário cirúrgico"
          detail="Não foi possível carregar tempos, checklist e equipe. Tente novamente."
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
      ) : (
        <>
          <section className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Situação do caso
              </p>
              <p className="mt-1 text-2xl font-semibold text-slate-900">{statusMeta.label}</p>
            </div>
            <StatusBadge meta={statusMeta} />
          </section>

          <section>
            <div className="mb-3 flex items-center gap-2">
              <Clock size={16} className="text-blue-600" />
              <h3 className="text-base font-semibold text-slate-900">Tempos cirúrgicos</h3>
            </div>
            <div className="space-y-3">
              <SurgeryTimeline times={timeline.times} />
              <RecordTimeControl
                caseId={caseId}
                times={timeline.times}
                canManage={canManage}
                onRecorded={load}
              />
            </div>
          </section>

          <section>
            <div className="mb-3 flex items-center gap-2">
              <ListChecks size={16} className="text-blue-600" />
              <h3 className="text-base font-semibold text-slate-900">
                Checklist de cirurgia segura (OMS)
              </h3>
            </div>
            <SurgeryChecklist
              caseId={caseId}
              confirmed={timeline.checklists}
              canManage={canManage}
              onConfirmed={load}
            />
          </section>

          <section>
            <div className="mb-3 flex items-center gap-2">
              <Users size={16} className="text-blue-600" />
              <h3 className="text-base font-semibold text-slate-900">Equipe cirúrgica</h3>
            </div>
            <SurgeryTeamPanel
              caseId={caseId}
              team={timeline.team}
              canManage={canManage}
              onChanged={load}
            />
          </section>
        </>
      )}
    </div>
  )
}
