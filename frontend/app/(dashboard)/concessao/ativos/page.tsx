'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import AssetList from '@/components/concession/AssetList'
import AssetFormModal from '@/components/concession/AssetFormModal'
import AssetMovementModal from '@/components/concession/AssetMovementModal'
import AssetMovementTimeline from '@/components/concession/AssetMovementTimeline'
import {
  ASSET_STATUS_OPTIONS,
  OWNERSHIP_OPTIONS,
  unwrap,
  type Asset,
  type FacilityOption,
  type Listish,
} from '@/components/concession/assetMeta'

const FILTER_SELECT_CLASS =
  'border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500'

export default function AtivosPage() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [statusFilter, setStatusFilter] = useState('')
  const [ownershipFilter, setOwnershipFilter] = useState('')

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Asset | null>(null)
  const [movingAsset, setMovingAsset] = useState<Asset | null>(null)
  const [historyAsset, setHistoryAsset] = useState<Asset | null>(null)

  const loadAssets = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<Listish<Asset>>('/api/v1/concession/assets/')
      setAssets(unwrap(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadFacilities = useCallback(async () => {
    try {
      const data = await apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/')
      setFacilities(unwrap(data))
    } catch {
      setFacilities([])
    }
  }, [])

  useEffect(() => {
    loadAssets()
    loadFacilities()
  }, [loadAssets, loadFacilities])

  const filtered = useMemo(
    () =>
      assets.filter(
        (a) =>
          (statusFilter === '' || a.status === statusFilter) &&
          (ownershipFilter === '' || a.ownership === ownershipFilter)
      ),
    [assets, statusFilter, ownershipFilter]
  )

  function openCreate() {
    setEditing(null)
    setFormOpen(true)
  }

  function openEdit(asset: Asset) {
    setEditing(asset)
    setFormOpen(true)
  }

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Frota / ativos em comodato</h1>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Equipamentos de imagem cedidos às unidades e seu histórico de movimentação.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          + Novo ativo
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <div>
          <label htmlFor="filter-status" className="sr-only">
            Filtrar por status
          </label>
          <select
            id="filter-status"
            className={FILTER_SELECT_CLASS}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Todos os status</option>
            {ASSET_STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="filter-ownership" className="sr-only">
            Filtrar por propriedade
          </label>
          <select
            id="filter-ownership"
            className={FILTER_SELECT_CLASS}
            value={ownershipFilter}
            onChange={(e) => setOwnershipFilter(e.target.value)}
          >
            <option value="">Todas as propriedades</option>
            {OWNERSHIP_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar ativos."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && assets.length === 0 && (
        <SectionState
          title="Nenhum ativo cadastrado ainda."
          detail='Clique em "+ Novo ativo" para registrar o primeiro equipamento em comodato.'
        />
      )}

      {!loading && !error && assets.length > 0 && filtered.length === 0 && (
        <SectionState
          title="Nenhum ativo corresponde aos filtros."
          detail="Ajuste o status ou a propriedade para ver mais equipamentos."
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <AssetList
          assets={filtered}
          facilities={facilities}
          onEdit={openEdit}
          onMove={setMovingAsset}
          onHistory={setHistoryAsset}
        />
      )}

      <AssetFormModal
        open={formOpen}
        asset={editing}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          loadAssets()
        }}
      />

      {movingAsset && (
        <AssetMovementModal
          open
          asset={movingAsset}
          assets={assets}
          onClose={() => setMovingAsset(null)}
          onSuccess={() => {
            setMovingAsset(null)
            loadAssets()
          }}
        />
      )}

      {historyAsset && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <h2 className="text-base font-semibold text-slate-900">Histórico de movimentação</h2>
                <p className="text-xs text-slate-500">
                  {historyAsset.asset_tag} — {historyAsset.model}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setHistoryAsset(null)}
                aria-label="Fechar"
                className="text-slate-400 hover:text-slate-600"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-5 py-4">
              <AssetMovementTimeline assetId={historyAsset.id} facilities={facilities} />
            </div>
          </div>
        </div>
      )}
    </PageShell>
  )
}
