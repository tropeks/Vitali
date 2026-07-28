'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import MaintenanceBoard from '@/components/concession/MaintenanceBoard'
import MaintenanceTicketFormModal from '@/components/concession/MaintenanceTicketFormModal'
import {
  MAINTENANCE_ENDPOINTS,
  unwrap,
  type AssetOption,
  type MaintenanceTicket,
} from '@/components/concession/maintenanceMeta'
import type { FacilityOption, Listish } from '@/components/concession/assetMeta'

export default function ManutencaoPage() {
  const [tickets, setTickets] = useState<MaintenanceTicket[]>([])
  const [assets, setAssets] = useState<AssetOption[]>([])
  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [formOpen, setFormOpen] = useState(false)

  const loadTickets = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<Listish<MaintenanceTicket>>(MAINTENANCE_ENDPOINTS.tickets)
      setTickets(unwrap(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadAssets = useCallback(async () => {
    try {
      const data = await apiFetch<Listish<AssetOption>>(MAINTENANCE_ENDPOINTS.assets)
      setAssets(unwrap(data))
    } catch {
      setAssets([])
    }
  }, [])

  const loadFacilities = useCallback(async () => {
    try {
      const data = await apiFetch<Listish<FacilityOption>>(MAINTENANCE_ENDPOINTS.facilities)
      setFacilities(unwrap(data))
    } catch {
      setFacilities([])
    }
  }, [])

  useEffect(() => {
    loadTickets()
    loadAssets()
    loadFacilities()
  }, [loadTickets, loadAssets, loadFacilities])

  function handleUpdated(updated: MaintenanceTicket) {
    setTickets((current) => current.map((t) => (t.id === updated.id ? updated : t)))
  }

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Manutenção</h1>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Chamados de manutenção da frota de equipamentos em comodato.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setFormOpen(true)}
          className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          + Novo ticket
        </button>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar os tickets de manutenção."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && tickets.length === 0 && (
        <SectionState
          title="Nenhum ticket de manutenção cadastrado ainda."
          detail='Clique em "+ Novo ticket" para abrir o primeiro chamado.'
        />
      )}

      {!loading && !error && tickets.length > 0 && (
        <MaintenanceBoard
          tickets={tickets}
          assets={assets}
          facilities={facilities}
          onUpdated={handleUpdated}
        />
      )}

      <MaintenanceTicketFormModal
        open={formOpen}
        assets={assets}
        facilities={facilities}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          loadTickets()
        }}
      />
    </PageShell>
  )
}
