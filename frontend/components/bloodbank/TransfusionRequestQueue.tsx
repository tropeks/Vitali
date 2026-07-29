'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import TransfusionRequestCard from './TransfusionRequestCard'
import ReserveBagModal from './ReserveBagModal'
import TransfusionCancelModal from './TransfusionCancelModal'
import NewTransfusionRequestModal from './NewTransfusionRequestModal'
import {
  apiErrorDetail,
  normalizeList,
  REQUEST_STATUS_FILTERS,
  type ListResponse,
  type TransfusionRequestDTO,
} from './bloodbank-types'

interface TransfusionRequestQueueProps {
  canManage: boolean
  canRequest: boolean
}

/**
 * Fila de requisições transfusionais — GET /api/v1/transfusion-requests/
 * filtered by status. The agência reserves (ReserveBagModal), liberates
 * (direct POST) and cancels (TransfusionCancelModal) each request when
 * `canManage`; the requesting médico opens a new requisição when `canRequest`.
 */
export default function TransfusionRequestQueue({
  canManage,
  canRequest,
}: TransfusionRequestQueueProps) {
  const [requests, setRequests] = useState<TransfusionRequestDTO[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [actionError, setActionError] = useState('')

  const [creating, setCreating] = useState(false)
  const [reserveFor, setReserveFor] = useState<TransfusionRequestDTO | null>(null)
  const [cancelFor, setCancelFor] = useState<TransfusionRequestDTO | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    setActionError('')
    const qs = statusFilter ? `?status=${statusFilter}` : ''
    try {
      const data = await apiFetch<ListResponse<TransfusionRequestDTO> | TransfusionRequestDTO[]>(
        `/api/v1/transfusion-requests/${qs}`
      )
      setRequests(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const liberar = useCallback(
    async (request: TransfusionRequestDTO) => {
      setActionError('')
      try {
        await apiFetch(`/api/v1/transfusion-requests/${request.id}/liberar/`, { method: 'POST' })
        load()
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setActionError(
            apiErrorDetail(err.body, 'Não é possível liberar esta requisição na situação atual.')
          )
        } else {
          setActionError('Não foi possível liberar a requisição. Tente novamente.')
        }
      }
    },
    [load]
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <select
          aria-label="Filtrar requisições por situação"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
        >
          {REQUEST_STATUS_FILTERS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        {canRequest && (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <Plus size={15} aria-hidden />
            Nova requisição
          </button>
        )}
      </div>

      {actionError && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
          {actionError}
        </p>
      )}

      {loading ? (
        <SectionState
          title="Carregando requisições transfusionais..."
          detail="Buscando a fila de requisições do banco de sangue."
        />
      ) : error ? (
        <SectionState
          title="Erro ao carregar as requisições"
          detail="Não foi possível carregar as requisições transfusionais. Tente novamente."
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
      ) : requests.length === 0 ? (
        <SectionState
          title="Nenhuma requisição"
          detail="Não há requisições transfusionais para a situação selecionada."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {requests.map((request) => (
            <TransfusionRequestCard
              key={request.id}
              request={request}
              canManage={canManage}
              onReserve={setReserveFor}
              onLiberar={liberar}
              onCancel={setCancelFor}
            />
          ))}
        </div>
      )}

      {creating && (
        <NewTransfusionRequestModal
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            load()
          }}
        />
      )}
      {reserveFor && (
        <ReserveBagModal
          request={reserveFor}
          onClose={() => setReserveFor(null)}
          onReserved={() => {
            setReserveFor(null)
            load()
          }}
        />
      )}
      {cancelFor && (
        <TransfusionCancelModal
          requestId={cancelFor.id}
          onClose={() => setCancelFor(null)}
          onCancelled={() => {
            setCancelFor(null)
            load()
          }}
        />
      )}
    </div>
  )
}
