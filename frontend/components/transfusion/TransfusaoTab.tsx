'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Droplet, Plus, RefreshCw, ScanLine } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import BedsideCheck from './BedsideCheck'
import ReactionForm from './ReactionForm'
import TransfusionRequestForm from './TransfusionRequestForm'
import {
  ADMIN_STATUS_META,
  REACTION_SEVERITY_OPTIONS,
  REACTION_TYPE_OPTIONS,
  crossmatchSummary,
  formatDateTime,
  labelOf,
  metaOf,
  normalizeList,
  requestStatusMeta,
  urgenciaMeta,
  type ListResponse,
  type TransfusionAdministration,
  type TransfusionReaction,
  type TransfusionRequest,
} from './transfusion-types'

interface TransfusaoTabProps {
  patientId: string
  /** Wristband/MRN scanned off the patient — prefills the bedside checagem. */
  patientBarcode: string
  /** Active order parent for a nova requisição (patient's open encounter). */
  encounterId: string | null
  /** `hemoterapia.read` — gates the whole read surface. */
  canRead: boolean
  /** `hemoterapia.manage` — gates nova requisição / checagem / reação. */
  canWrite: boolean
}

/** Checagem beira-leito is available once the requisição has been liberada. */
function isCheckable(request: TransfusionRequest): boolean {
  return request.status === 'liberada'
}

/**
 * Transfusão tab (H6) — the clinical bedside counterpart of the `/banco-de-sangue`
 * agency panel. Lists the patient's requisições transfusionais (component /
 * urgência / status / prova cruzada), lets a nova requisição be opened, runs the
 * beira-leito checagem dos 5 certos against a bolsa the nurse picks from stock,
 * and shows the administered transfusions with the ability to register a reação
 * (hemovigilância). Read requires `hemoterapia.read`; writes are gated further.
 * The backend enforces every gate regardless.
 */
export default function TransfusaoTab({
  patientId,
  patientBarcode,
  encounterId,
  canRead,
  canWrite,
}: TransfusaoTabProps) {
  const [requests, setRequests] = useState<TransfusionRequest[]>([])
  const [administrations, setAdministrations] = useState<TransfusionAdministration[]>([])
  const [reactions, setReactions] = useState<TransfusionReaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [checking, setChecking] = useState<TransfusionRequest | null>(null)
  const [reacting, setReacting] = useState<TransfusionAdministration | null>(null)

  const load = useCallback(async () => {
    if (!patientId || !canRead) return
    setLoading(true)
    setError(false)
    try {
      const [reqs, admins, reacs] = await Promise.all([
        apiFetch<ListResponse<TransfusionRequest> | TransfusionRequest[]>(
          `/api/v1/transfusion-requests/?patient=${patientId}`,
        ),
        apiFetch<ListResponse<TransfusionAdministration> | TransfusionAdministration[]>(
          `/api/v1/transfusion-administrations/?patient=${patientId}`,
        ),
        apiFetch<ListResponse<TransfusionReaction> | TransfusionReaction[]>(
          `/api/v1/transfusion-reactions/?patient=${patientId}`,
        ),
      ])
      setRequests(normalizeList(reqs))
      setAdministrations(normalizeList(admins))
      setReactions(normalizeList(reacs))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId, canRead])

  useEffect(() => {
    load()
  }, [load])

  /** requisição pk → its component display, to label an administração. */
  const componentByRequest = useMemo(() => {
    const map = new Map<string, string>()
    for (const request of requests) {
      if (request.component_display) map.set(request.id, request.component_display)
    }
    return map
  }, [requests])

  /** administração pk → its recorded reação (if any). */
  const reactionByAdmin = useMemo(() => {
    const map = new Map<string, TransfusionReaction>()
    for (const reaction of reactions) {
      if (reaction.administration) map.set(reaction.administration, reaction)
    }
    return map
  }, [reactions])

  if (!canRead) {
    return (
      <SectionState
        title="Sem acesso à hemoterapia"
        detail="Você não tem permissão para visualizar dados de transfusão (hemoterapia.read)."
      />
    )
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando transfusão..."
        detail="Buscando as requisições transfusionais e as transfusões do paciente."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar transfusão"
        detail="Não foi possível carregar os dados de hemoterapia. Tente novamente."
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
    <div className="space-y-6">
      {/* ── requisições transfusionais ─────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-neu-ink">Requisições transfusionais</h3>
          {canWrite && (
            <button
              type="button"
              onClick={() => setShowNew(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-neu-brand bg-neu-brand px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
            >
              <Plus size={14} />
              Nova requisição
            </button>
          )}
        </div>

        {requests.length === 0 ? (
          <SectionState
            title="Sem requisição transfusional"
            detail="Nenhuma requisição de hemocomponente vinculada ao paciente."
          />
        ) : (
          <ul className="space-y-2" aria-label="Requisições transfusionais">
            {requests.map((request) => {
              const compat = crossmatchSummary(request.crossmatches)
              return (
                <li
                  key={request.id}
                  className="rounded-lg border border-slate-200 bg-white px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Droplet size={15} className="shrink-0 text-red-600" />
                    <span className="text-sm font-semibold text-neu-ink">
                      {request.component_display || request.component_code || 'Hemocomponente'}
                    </span>
                    <span className="text-xs text-neu-inkMuted">{request.quantidade} un</span>
                    <StatusBadge meta={urgenciaMeta(request.urgencia)} />
                    <StatusBadge meta={requestStatusMeta(request.status)} />
                    {compat && <StatusBadge meta={compat} />}
                  </div>
                  {request.indicacao && (
                    <p className="mt-2 text-xs text-neu-inkSoft">{request.indicacao}</p>
                  )}
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <span className="text-xs text-neu-inkMuted">
                      {formatDateTime(request.created_at)}
                    </span>
                    {canWrite && isCheckable(request) && (
                      <button
                        type="button"
                        onClick={() => setChecking(request)}
                        className="inline-flex items-center gap-1.5 rounded-md border border-neu-brand px-3 py-1.5 text-xs font-semibold text-neu-brand hover:bg-blue-50"
                      >
                        <ScanLine size={14} />
                        Checagem beira-leito
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* ── transfusões administradas ──────────────────────────────────────── */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-neu-ink">Transfusões administradas</h3>
        {administrations.length === 0 ? (
          <SectionState
            title="Sem transfusão administrada"
            detail="Nenhuma transfusão administrada registrada para o paciente."
          />
        ) : (
          <ul className="space-y-2" aria-label="Transfusões administradas">
            {administrations.map((administration) => {
              const reaction = reactionByAdmin.get(administration.id) ?? null
              const componentDisplay =
                (administration.request && componentByRequest.get(administration.request)) ||
                'Hemocomponente'
              return (
                <li
                  key={administration.id}
                  className="rounded-lg border border-slate-200 bg-white px-4 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Droplet size={15} className="shrink-0 text-red-600" />
                    <span className="text-sm font-semibold text-neu-ink">{componentDisplay}</span>
                    {administration.bag_identifier && (
                      <span className="text-xs text-neu-inkMuted">
                        Bolsa {administration.bag_identifier}
                      </span>
                    )}
                    <StatusBadge meta={metaOf(ADMIN_STATUS_META, administration.status)} />
                    {reaction && (
                      <StatusBadge
                        meta={{
                          label: `Reação: ${labelOf(REACTION_TYPE_OPTIONS, reaction.tipo)} (${labelOf(
                            REACTION_SEVERITY_OPTIONS,
                            reaction.gravidade,
                          )})`,
                          badgeClass: 'border-red-300 bg-red-100 text-red-800',
                        }}
                      />
                    )}
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <span className="text-xs text-neu-inkMuted">
                      {formatDateTime(administration.started_at)}
                    </span>
                    {canWrite && !reaction && (
                      <button
                        type="button"
                        onClick={() => setReacting(administration)}
                        className="rounded-md border border-red-300 px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50"
                      >
                        Registrar reação
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {showNew && (
        <TransfusionRequestForm
          patientId={patientId}
          encounterId={encounterId}
          onClose={() => setShowNew(false)}
          onCreated={(request) => {
            setRequests((current) => [request, ...current])
            setShowNew(false)
          }}
        />
      )}

      {checking && (
        <BedsideCheck
          request={checking}
          patientBarcode={patientBarcode}
          onClose={() => setChecking(null)}
          onChecked={() => {
            setChecking(null)
            void load()
          }}
        />
      )}

      {reacting && (
        <ReactionForm
          administration={reacting}
          onClose={() => setReacting(null)}
          onSaved={(_administration, reaction) => {
            setReactions((current) => [reaction, ...current])
            setReacting(null)
          }}
        />
      )}
    </div>
  )
}
