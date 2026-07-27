'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { BedDouble, LogOut, RefreshCw, UserRound } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import AdmissionTimeline from './AdmissionTimeline'
import AdmitPatientModal from './AdmitPatientModal'
import {
  ADMISSION_SOURCE_OPTIONS,
  ADMISSION_STATUS_META,
  DISPOSITION_OPTIONS,
  formatDateTime,
  formatLOS,
  labelOf,
  normalizeList,
  type Admission,
  type AdmissionEvent,
  type BoardResponse,
  type ListResponse,
  type ProfessionalOption,
} from './admission-types'

interface Props {
  patientId: string
  /** `beds.read` — gates the read-only stay summary + ADT timeline. */
  canRead: boolean
  /** `adt.admit` — gates the Admitir action. */
  canAdmit: boolean
  /** `adt.discharge` — gates the Dar alta action. */
  canDischarge: boolean
}

interface Enrichment {
  bedLabels: Record<string, string>
  unitName: string | null
  bedIdentifier: string | null
  admittingName: string | null
  attendingName: string | null
}

const EMPTY_ENRICHMENT: Enrichment = {
  bedLabels: {},
  unitName: null,
  bedIdentifier: null,
  admittingName: null,
  attendingName: null,
}

function buildEnrichment(
  admission: Admission,
  board: BoardResponse | null,
  admittingProf: ProfessionalOption | null,
  attendingProf: ProfessionalOption | null,
): Enrichment {
  const bedLabels: Record<string, string> = {}
  let unitName: string | null = null
  let bedIdentifier: string | null = null
  for (const unit of board?.units ?? []) {
    for (const room of unit.rooms ?? []) {
      for (const bed of room.beds ?? []) {
        bedLabels[bed.id] = bed.identifier
        if (admission.current_bed && bed.id === admission.current_bed) {
          unitName = unit.name
          bedIdentifier = bed.identifier
        }
      }
    }
  }
  return {
    bedLabels,
    unitName,
    bedIdentifier,
    admittingName: admittingProf?.user_name ?? null,
    attendingName: attendingProf?.user_name ?? null,
  }
}

function StayField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm font-medium text-slate-900">{value || '—'}</dd>
    </div>
  )
}

/**
 * Internação panel (L5) — the patient chart's ADT surface.
 *
 * Reads the patient's active stay (`GET /admissions/?patient=&status=admitted`).
 * When admitted: stay summary (leito/unidade, responsável, fonte, admissão,
 * LOS) + ADT timeline (`/admission-events/`) + a Dar alta action
 * (`adt.discharge`). When not admitted: an Admitir action (`adt.admit`) opening
 * {@link AdmitPatientModal}. The read view requires `beds.read`; write actions
 * are gated further. The backend enforces every gate regardless.
 */
export default function AdmissionPanel({ patientId, canRead, canAdmit, canDischarge }: Props) {
  const [admission, setAdmission] = useState<Admission | null>(null)
  const [events, setEvents] = useState<AdmissionEvent[]>([])
  const [enrichment, setEnrichment] = useState<Enrichment>(EMPTY_ENRICHMENT)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [admitting, setAdmitting] = useState(false)
  const [dischargeOpen, setDischargeOpen] = useState(false)
  const [disposition, setDisposition] = useState('alta_melhorada')
  const [reason, setReason] = useState('')
  const [dischargeSaving, setDischargeSaving] = useState(false)
  const [dischargeError, setDischargeError] = useState('')

  const load = useCallback(async () => {
    if (!patientId || !canRead) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse<Admission> | Admission[]>(
        `/api/v1/admissions/?patient=${patientId}&status=admitted`,
      )
      const active = normalizeList(data)[0] ?? null
      setAdmission(active)
      if (!active) {
        setEvents([])
        setEnrichment(EMPTY_ENRICHMENT)
        return
      }
      const [eventsResult, boardResult, admittingResult, attendingResult] =
        await Promise.allSettled([
          apiFetch<ListResponse<AdmissionEvent> | AdmissionEvent[]>(
            `/api/v1/admission-events/?admission=${active.id}`,
          ),
          apiFetch<BoardResponse>('/api/v1/beds/board/'),
          apiFetch<ProfessionalOption>(
            `/api/v1/professionals/${active.admitting_professional}/`,
          ),
          apiFetch<ProfessionalOption>(
            `/api/v1/professionals/${active.attending_professional}/`,
          ),
        ])
      setEvents(eventsResult.status === 'fulfilled' ? normalizeList(eventsResult.value) : [])
      setEnrichment(
        buildEnrichment(
          active,
          boardResult.status === 'fulfilled' ? boardResult.value : null,
          admittingResult.status === 'fulfilled' ? admittingResult.value : null,
          attendingResult.status === 'fulfilled' ? attendingResult.value : null,
        ),
      )
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId, canRead])

  useEffect(() => {
    load()
  }, [load])

  const los = useMemo(
    () =>
      admission
        ? formatLOS(admission.admission_datetime, admission.actual_discharge_datetime)
        : '—',
    [admission],
  )

  const submitDischarge = async () => {
    if (!admission) return
    setDischargeSaving(true)
    setDischargeError('')
    try {
      await apiFetch(`/api/v1/admissions/${admission.id}/discharge/`, {
        method: 'POST',
        body: JSON.stringify({ disposition, reason: reason.trim() }),
      })
      setDischargeOpen(false)
      setReason('')
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setDischargeError('Não foi possível dar alta: internação já encerrada.')
      } else {
        setDischargeError('Não foi possível registrar a alta. Tente novamente.')
      }
    } finally {
      setDischargeSaving(false)
    }
  }

  if (!canRead) {
    return (
      <SectionState
        title="Sem acesso à internação"
        detail="Você não tem permissão para visualizar dados de internação (beds.read)."
      />
    )
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando internação..."
        detail="Buscando a internação ativa e o histórico ADT do paciente."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar internação"
        detail="Não foi possível carregar os dados de internação. Tente novamente."
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

  // ── No active stay → Admitir ────────────────────────────────────────────────
  if (!admission) {
    return (
      <div className="space-y-4">
        <SectionState
          title="Paciente não internado"
          detail="Nenhuma internação ativa. Admita o paciente para iniciar o fluxo ADT."
        />
        {canAdmit && (
          <button
            type="button"
            onClick={() => setAdmitting(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
          >
            <BedDouble size={15} />
            Admitir paciente
          </button>
        )}
        {admitting && (
          <AdmitPatientModal
            patientId={patientId}
            onClose={() => setAdmitting(false)}
            onAdmitted={load}
          />
        )}
      </div>
    )
  }

  // ── Active stay → summary + timeline + discharge ────────────────────────────
  const statusMeta = ADMISSION_STATUS_META[admission.status] ?? {
    label: admission.status,
    badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <BedDouble size={17} className="text-blue-600" />
            <h2 className="text-base font-semibold text-slate-900">Internação ativa</h2>
          </div>
          <StatusBadge meta={statusMeta} />
        </div>
        <dl className="grid grid-cols-1 gap-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
          <StayField
            label="Leito / unidade"
            value={
              enrichment.bedIdentifier
                ? `${enrichment.bedIdentifier}${enrichment.unitName ? ` — ${enrichment.unitName}` : ''}`
                : null
            }
          />
          <StayField label="Responsável" value={enrichment.attendingName} />
          <StayField label="Internador" value={enrichment.admittingName} />
          <StayField
            label="Fonte"
            value={labelOf(ADMISSION_SOURCE_OPTIONS, admission.admission_source)}
          />
          <StayField
            label="Data de admissão"
            value={formatDateTime(admission.admission_datetime)}
          />
          <StayField label="Tempo de permanência (LOS)" value={los} />
        </dl>

        {canDischarge && (
          <div className="border-t border-slate-100 px-4 py-3">
            {!dischargeOpen ? (
              <button
                type="button"
                onClick={() => setDischargeOpen(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                <LogOut size={15} />
                Dar alta
              </button>
            ) : (
              <div className="space-y-3">
                <p className="text-sm font-semibold text-slate-900">Registrar alta</p>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="block text-xs font-semibold text-slate-600">
                    Desfecho
                    <select
                      value={disposition}
                      onChange={(event) => setDisposition(event.target.value)}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                    >
                      {DISPOSITION_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs font-semibold text-slate-600">
                    Motivo (opcional)
                    <input
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                    />
                  </label>
                </div>
                {dischargeError && (
                  <p className="text-xs font-semibold text-red-700">{dischargeError}</p>
                )}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={submitDischarge}
                    disabled={dischargeSaving}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {dischargeSaving ? 'Registrando...' : 'Confirmar alta'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDischargeOpen(false)
                      setDischargeError('')
                    }}
                    className="text-sm font-semibold text-slate-500 hover:underline"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-center gap-2">
          <UserRound size={16} className="text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-900">Linha do tempo ADT</h3>
        </div>
        <AdmissionTimeline events={events} bedLabels={enrichment.bedLabels} />
      </section>
    </div>
  )
}
