'use client'

import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, LogOut, RefreshCw, Siren, Stethoscope } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import EmergencyClassificationHistory from './EmergencyClassificationHistory'
import EmergencyReclassifyModal from './EmergencyReclassifyModal'
import {
  acuityMeta,
  DISPOSITION_OPTIONS,
  formatDateTime,
  labelOf,
  MODE_OF_ARRIVAL_OPTIONS,
  normalizeList,
  statusMeta,
  type BedOption,
  type EmergencyEncounter,
  type ListResponse,
  type ProfessionalOption,
  type RiskClassification,
} from './emergency-chart-types'

interface Props {
  boletimId: string
  /** `emergency.classify` — gates the Reclassificar action. */
  canClassify: boolean
  /** `emergency.manage` — gates the Desfecho (encerrar) action. */
  canManage: boolean
  onBack: () => void
}

/**
 * Detalhe do boletim de emergência (E5) — arrival data + the destaque of the
 * current acuity + the append-only classification history
 * (`/risk-classifications/?boletim=`). Reclassificar (emergency.classify) opens
 * {@link EmergencyReclassifyModal} (append). Desfecho (emergency.manage) is an
 * inline form: `internacao` + a free bed → the internação bridge; a 409 (leito
 * ocupado / transição ilegal) surfaces inline. An `encerrado` boletim shows the
 * desfecho + internação hint instead of the write actions.
 */
export default function EmergencyCaseDetail({ boletimId, canClassify, canManage, onBack }: Props) {
  const [boletim, setBoletim] = useState<EmergencyEncounter | null>(null)
  const [history, setHistory] = useState<RiskClassification[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [reclassifyOpen, setReclassifyOpen] = useState(false)

  const [closeOpen, setCloseOpen] = useState(false)
  const [disposition, setDisposition] = useState(DISPOSITION_OPTIONS[0].value)
  const [beds, setBeds] = useState<BedOption[]>([])
  const [bedId, setBedId] = useState('')
  const [admitting, setAdmitting] = useState<ProfessionalOption | null>(null)
  const [attending, setAttending] = useState<ProfessionalOption | null>(null)
  const [reason, setReason] = useState('')
  const [closeSaving, setCloseSaving] = useState(false)
  const [closeError, setCloseError] = useState('')

  const load = useCallback(async () => {
    if (!boletimId) return
    setLoading(true)
    setError(false)
    try {
      const boletimData = await apiFetch<EmergencyEncounter>(
        `/api/v1/emergency-encounters/${boletimId}/`,
      )
      setBoletim(boletimData)
      const historyResult = await apiFetch<
        ListResponse<RiskClassification> | RiskClassification[]
      >(`/api/v1/risk-classifications/?boletim=${boletimId}`)
      setHistory(normalizeList(historyResult))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [boletimId])

  useEffect(() => {
    load()
  }, [load])

  const loadBeds = useCallback(async () => {
    try {
      const data = await apiFetch<ListResponse<BedOption> | BedOption[]>(
        '/api/v1/beds/?status=livre',
      )
      setBeds(normalizeList(data))
    } catch {
      setBeds([])
    }
  }, [])

  const openClose = () => {
    setCloseOpen(true)
    setCloseError('')
    void loadBeds()
  }

  const professionalLabel = (professional: ProfessionalOption) =>
    professional.user_name ||
    (professional.council_number ? `Registro ${professional.council_number}` : professional.id)

  const submitClose = async () => {
    setCloseSaving(true)
    setCloseError('')
    const body: Record<string, string> = { disposition }
    if (disposition === 'internacao' && bedId) {
      if (!admitting || !attending) {
        setCloseError('Internação com leito exige profissional internador e responsável.')
        setCloseSaving(false)
        return
      }
      body.bed = bedId
      body.admitting_professional = admitting.id
      body.attending_professional = attending.id
    }
    if (reason.trim()) body.reason = reason.trim()
    try {
      await apiFetch(`/api/v1/emergency-encounters/${boletimId}/close/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setCloseOpen(false)
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCloseError('Não foi possível encerrar: leito ocupado ou transição inválida.')
        await loadBeds()
      } else {
        setCloseError('Não foi possível registrar o desfecho. Revise os dados e tente novamente.')
      }
    } finally {
      setCloseSaving(false)
    }
  }

  const BackButton = (
    <button
      type="button"
      onClick={onBack}
      className="inline-flex items-center gap-1 text-sm font-semibold text-blue-600 hover:underline"
    >
      <ArrowLeft size={15} />
      Voltar aos boletins
    </button>
  )

  if (loading) {
    return (
      <div className="space-y-4">
        {BackButton}
        <SectionState title="Carregando boletim..." detail="Buscando os dados do atendimento de emergência." />
      </div>
    )
  }

  if (error || !boletim) {
    return (
      <div className="space-y-4">
        {BackButton}
        <SectionState
          title="Erro ao carregar boletim"
          detail="Não foi possível carregar o atendimento de emergência. Tente novamente."
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
      </div>
    )
  }

  const current = boletim.current_classification ?? null
  const isClosed = boletim.status === 'encerrado'

  return (
    <div className="space-y-6">
      {BackButton}

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <Siren size={17} className="text-red-600" />
            <h2 className="text-base font-semibold text-slate-900">Atendimento de emergência</h2>
          </div>
          <StatusBadge meta={statusMeta(boletim.status)} />
        </div>

        <dl className="grid grid-cols-1 gap-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Chegada</dt>
            <dd className="mt-1 text-sm font-medium text-slate-900">
              {formatDateTime(boletim.arrival_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Meio de chegada</dt>
            <dd className="mt-1 text-sm font-medium text-slate-900">
              {labelOf(MODE_OF_ARRIVAL_OPTIONS, boletim.mode_of_arrival)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Queixa principal</dt>
            <dd className="mt-1 text-sm font-medium text-slate-900">
              {boletim.chief_complaint || 'Não informada'}
            </dd>
          </div>
        </dl>

        <div className="border-t border-slate-100 px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Acuidade atual</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge meta={acuityMeta(current?.acuity_level)} />
            {current ? (
              <>
                <span className="text-xs text-slate-500">Tempo-alvo {current.target_minutes} min</span>
                <span className="text-xs text-slate-400">·</span>
                <span className="text-xs text-slate-600">
                  {current.flowchart_code || 'Fluxograma'} · {current.discriminator_code || 'Discriminador'}
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-500">Boletim ainda não classificado.</span>
            )}
          </div>
        </div>

        {isClosed && (
          <div className="border-t border-slate-100 px-4 py-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Desfecho</p>
            <p className="mt-1 text-sm font-medium text-slate-900">
              {labelOf(DISPOSITION_OPTIONS, boletim.disposition)}
            </p>
            {boletim.admission && (
              <p className="mt-1 text-xs text-slate-500">
                Internação gerada (ADT): {boletim.admission}
              </p>
            )}
          </div>
        )}

        {!isClosed && (canClassify || canManage) && (
          <div className="flex flex-wrap gap-2 border-t border-slate-100 px-4 py-3">
            {canClassify && (
              <button
                type="button"
                onClick={() => setReclassifyOpen(true)}
                className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
              >
                <Stethoscope size={15} />
                Reclassificar
              </button>
            )}
            {canManage && !closeOpen && (
              <button
                type="button"
                onClick={openClose}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                <LogOut size={15} />
                Desfecho
              </button>
            )}
          </div>
        )}

        {!isClosed && canManage && closeOpen && (
          <div className="space-y-3 border-t border-slate-100 px-4 py-4">
            <p className="text-sm font-semibold text-slate-900">Registrar desfecho</p>
            <label className="block text-xs font-semibold text-slate-600">
              Desfecho
              <select
                aria-label="Desfecho"
                value={disposition}
                onChange={(event) => setDisposition(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm sm:max-w-xs"
              >
                {DISPOSITION_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            {disposition === 'internacao' && (
              <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                <p className="text-xs text-slate-600">
                  Escolha um leito livre para acionar a internação (ADT) agora, ou deixe em branco
                  para internar depois.
                </p>
                <label className="block text-xs font-semibold text-slate-600">
                  Leito livre
                  <select
                    aria-label="Leito livre"
                    value={bedId}
                    onChange={(event) => setBedId(event.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  >
                    <option value="">
                      {beds.length === 0 ? 'Sem leito livre (internar depois)' : 'Selecione um leito'}
                    </option>
                    {beds.map((bed) => (
                      <option key={bed.id} value={bed.id}>
                        {bed.identifier}
                      </option>
                    ))}
                  </select>
                </label>
                {bedId && (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <RemoteCombobox<ProfessionalOption>
                      label="Profissional internador"
                      endpoint="/api/v1/professionals/"
                      value={admitting}
                      getKey={(item) => item.id}
                      getLabel={professionalLabel}
                      onChange={setAdmitting}
                      placeholder="Internador..."
                    />
                    <RemoteCombobox<ProfessionalOption>
                      label="Profissional responsável"
                      endpoint="/api/v1/professionals/"
                      value={attending}
                      getKey={(item) => item.id}
                      getLabel={professionalLabel}
                      onChange={setAttending}
                      placeholder="Responsável..."
                    />
                  </div>
                )}
              </div>
            )}

            <label className="block text-xs font-semibold text-slate-600">
              Motivo (opcional)
              <input
                aria-label="Motivo"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            {closeError && <p className="text-xs font-semibold text-red-700">{closeError}</p>}

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={submitClose}
                disabled={closeSaving}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {closeSaving ? 'Registrando...' : 'Confirmar desfecho'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setCloseOpen(false)
                  setCloseError('')
                }}
                className="text-sm font-semibold text-slate-500 hover:underline"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-slate-900">
          Histórico de classificações (append-only)
        </h3>
        <EmergencyClassificationHistory classifications={history} />
      </section>

      {reclassifyOpen && (
        <EmergencyReclassifyModal
          boletimId={boletimId}
          onClose={() => setReclassifyOpen(false)}
          onClassified={load}
        />
      )}
    </div>
  )
}
