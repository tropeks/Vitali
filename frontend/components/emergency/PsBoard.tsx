'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, RefreshCw, Siren } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import PsQueueRow from './PsQueueRow'
import OpenBoletimModal from './OpenBoletimModal'
import TriageClassifyModal from './TriageClassifyModal'
import DispositionModal from './DispositionModal'
import {
  ACUITY_META,
  ACUITY_ORDER,
  type BoardResponse,
  type QueueRow,
} from './ps-board-types'

interface PsBoardProps {
  canManage: boolean
  canClassify: boolean
}

const EMPTY_COUNTS = { vermelho: 0, laranja: 0, amarelo: 0, verde: 0, azul: 0 }
const POLL_MS = 30_000

/**
 * Fila do Pronto-Socorro — the Manchester-ordered board (não-classificados
 * primeiro, depois vermelho→azul, depois chegada), coloured per acuidade with an
 * `overdue` highlight. Consumes GET /emergency-encounters/board/ with a 30s poll
 * and a refetch after every action. Abrir boletim / Classificar / Chamar /
 * Desfecho are gated by `canManage` / `canClassify`.
 */
export default function PsBoard({ canManage, canClassify }: PsBoardProps) {
  const [board, setBoard] = useState<BoardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [actionError, setActionError] = useState('')

  const [opening, setOpening] = useState(false)
  const [classifyFor, setClassifyFor] = useState<QueueRow | null>(null)
  const [closeFor, setCloseFor] = useState<QueueRow | null>(null)

  // A ref lets the poll refetch silently without re-subscribing the interval.
  const silentLoad = useRef<() => void>(() => {})

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<BoardResponse>('/api/v1/emergency-encounters/board/')
      setBoard(data)
    } catch {
      if (!silent) setError(true)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    silentLoad.current = () => void load(true)
  }, [load])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const id = setInterval(() => silentLoad.current(), POLL_MS)
    return () => clearInterval(id)
  }, [])

  const afterAction = useCallback(() => {
    setOpening(false)
    setClassifyFor(null)
    setCloseFor(null)
    load(true)
  }, [load])

  const startAttendance = useCallback(
    async (row: QueueRow) => {
      setActionError('')
      try {
        await apiFetch(`/api/v1/emergency-encounters/${row.boletim_id}/start-attendance/`, {
          method: 'POST',
          body: JSON.stringify({}),
        })
        load(true)
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setActionError('Não é possível chamar este paciente na situação atual.')
        } else {
          setActionError('Não foi possível chamar o paciente. Tente novamente.')
        }
      }
    },
    [load],
  )

  const counts = board?.counts ?? EMPTY_COUNTS
  const queue = board?.queue ?? []

  return (
    <div className="space-y-4">
      {/* Counts header + Abrir boletim */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {ACUITY_ORDER.map((level) => (
            <span
              key={level}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${ACUITY_META[level].badgeClass}`}
            >
              {ACUITY_META[level].label}
              <span className="font-bold tabular-nums">{counts[level]}</span>
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
            Aguardando classificação
            <span className="font-bold tabular-nums">{board?.unclassified ?? 0}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-red-400 bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-800">
            Tempo-alvo estourado
            <span className="font-bold tabular-nums">{board?.overdue ?? 0}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-neu-inkSoft">
            Total
            <span className="font-bold tabular-nums">{board?.total ?? 0}</span>
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => load()}
            aria-label="Atualizar fila"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-neu-inkSoft hover:bg-slate-50"
          >
            <RefreshCw size={14} aria-hidden />
            Atualizar
          </button>
          {canManage && (
            <button
              type="button"
              onClick={() => setOpening(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
            >
              <Plus size={15} aria-hidden />
              Abrir boletim
            </button>
          )}
        </div>
      </div>

      {actionError && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
          {actionError}
        </p>
      )}

      {loading ? (
        <SectionState
          title="Carregando a fila do pronto-socorro..."
          detail="Buscando os boletins ativos e a classificação de risco."
        />
      ) : error ? (
        <SectionState
          title="Erro ao carregar a fila do pronto-socorro"
          detail="Não foi possível carregar os boletins. Tente novamente."
          tone="critical"
          action={
            <button
              onClick={() => load()}
              className="inline-flex items-center gap-2 text-xs font-semibold text-red-700 hover:underline"
            >
              <RefreshCw size={13} />
              Tentar novamente
            </button>
          }
        />
      ) : queue.length === 0 ? (
        <SectionState
          title="Fila vazia"
          detail="Nenhum boletim ativo no pronto-socorro no momento."
          action={
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-neu-inkMuted">
              <Siren size={13} aria-hidden />
              Abra um boletim ao receber um paciente.
            </span>
          }
        />
      ) : (
        <ul className="space-y-2">
          {queue.map((row) => (
            <PsQueueRow
              key={row.boletim_id}
              row={row}
              canManage={canManage}
              canClassify={canClassify}
              onClassify={setClassifyFor}
              onStartAttendance={startAttendance}
              onClose={setCloseFor}
            />
          ))}
        </ul>
      )}

      {opening && (
        <OpenBoletimModal onClose={() => setOpening(false)} onOpened={afterAction} />
      )}
      {classifyFor && (
        <TriageClassifyModal
          boletimId={classifyFor.boletim_id}
          patientName={classifyFor.patient.name}
          onClose={() => setClassifyFor(null)}
          onClassified={afterAction}
        />
      )}
      {closeFor && (
        <DispositionModal
          boletimId={closeFor.boletim_id}
          patientName={closeFor.patient.name}
          onClose={() => setCloseFor(null)}
          onClosed={afterAction}
        />
      )}
    </div>
  )
}
