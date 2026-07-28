'use client'

import { useState } from 'react'
import { apiFetch } from '@/lib/api'
import { StatusBadge } from '@/components/shared'
import MaintenanceCompleteModal from './MaintenanceCompleteModal'
import {
  MAINTENANCE_COLUMNS,
  MAINTENANCE_ENDPOINTS,
  MAINTENANCE_STATUS_META,
  assetLabel,
  facilityName,
  formatBRL,
  type AssetOption,
  type MaintenanceTicket,
} from './maintenanceMeta'
import type { FacilityOption } from './assetMeta'

/**
 * MaintenanceBoard — Kanban grouping of MaintenanceTicket by status
 * (Abertos / Em andamento / Concluídos / Cancelados). Each card exposes the
 * B0 transitions: Iniciar (POST .../start/, OPEN → IN_PROGRESS) directly, and
 * Concluir (POST .../complete/, → COMPLETED) via a small modal that collects
 * the optional resolution/cost.
 */

export interface MaintenanceBoardProps {
  tickets: MaintenanceTicket[]
  assets: AssetOption[]
  facilities: FacilityOption[]
  onUpdated: (ticket: MaintenanceTicket) => void
}

export default function MaintenanceBoard({
  tickets,
  assets,
  facilities,
  onUpdated,
}: MaintenanceBoardProps) {
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [completingTicket, setCompletingTicket] = useState<MaintenanceTicket | null>(null)

  async function handleStart(ticket: MaintenanceTicket) {
    setBusyId(ticket.id)
    setError(null)
    try {
      const updated = await apiFetch<MaintenanceTicket>(
        `${MAINTENANCE_ENDPOINTS.tickets}${ticket.id}/start/`,
        { method: 'POST', body: JSON.stringify({}) }
      )
      onUpdated(updated)
    } catch {
      setError('Erro ao iniciar o chamado.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {MAINTENANCE_COLUMNS.map((column) => {
          const columnTickets = tickets.filter((t) => t.status === column.status)
          return (
            <div key={column.status} className="rounded-lg border border-white bg-neu-panel">
              <div className="flex items-center justify-between border-b border-white px-4 py-3">
                <h3 className="text-sm font-semibold text-neu-ink">{column.title}</h3>
                <span className="text-xs font-medium text-neu-inkMuted">{columnTickets.length}</span>
              </div>
              <div className="space-y-2 p-3">
                {columnTickets.length === 0 && (
                  <p className="text-xs text-neu-inkMuted">Nenhum chamado.</p>
                )}
                {columnTickets.map((ticket) => (
                  <div
                    key={ticket.id}
                    className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium text-neu-ink">
                        {assetLabel(ticket.asset, assets)}
                      </p>
                      <StatusBadge meta={MAINTENANCE_STATUS_META[ticket.status]} />
                    </div>
                    <p className="mt-1 text-xs text-neu-inkMuted">
                      {facilityName(ticket.facility, facilities)}
                    </p>
                    <p className="mt-2 text-sm text-neu-inkSoft">{ticket.description || '—'}</p>

                    {(ticket.cost != null || ticket.evidence_url) && (
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-neu-inkMuted">
                        {ticket.cost != null && (
                          <span className="tabular-nums">{formatBRL(ticket.cost)}</span>
                        )}
                        {ticket.evidence_url && (
                          <a
                            href={ticket.evidence_url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-neu-brand hover:underline"
                          >
                            Ver evidência
                          </a>
                        )}
                      </div>
                    )}

                    {ticket.status === 'OPEN' && (
                      <div className="mt-3 flex justify-end">
                        <button
                          type="button"
                          disabled={busyId === ticket.id}
                          onClick={() => handleStart(ticket)}
                          className="rounded-lg bg-neu-brand px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                        >
                          {busyId === ticket.id ? 'Iniciando...' : 'Iniciar'}
                        </button>
                      </div>
                    )}

                    {ticket.status === 'IN_PROGRESS' && (
                      <div className="mt-3 flex justify-end">
                        <button
                          type="button"
                          onClick={() => setCompletingTicket(ticket)}
                          className="rounded-lg bg-neu-brand px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
                        >
                          Concluir
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {completingTicket && (
        <MaintenanceCompleteModal
          open
          ticket={completingTicket}
          onClose={() => setCompletingTicket(null)}
          onSuccess={(updated) => {
            setCompletingTicket(null)
            onUpdated(updated)
          }}
        />
      )}
    </div>
  )
}
