'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import RequisitionList, { type RequisitionAction } from '@/components/concession/RequisitionList'
import RequisitionBuilder from '@/components/concession/RequisitionBuilder'
import PickPanel from '@/components/concession/PickPanel'
import DispatchList from '@/components/concession/DispatchList'
import DispatchForm from '@/components/concession/DispatchForm'
import DeliveryModal from '@/components/concession/DeliveryModal'
import PodViewer from '@/components/concession/PodViewer'
import {
  LOGISTICS_ENDPOINTS,
  unwrap,
  type Listish,
  type SupplyRequisition,
  type PickList,
  type Dispatch,
  type ProofOfDelivery,
  type DispatchDiscrepancy,
  type FacilityOption,
  type MaterialOption,
  type WarehouseOption,
  type StockItemOption,
} from '@/components/concession/logisticsMeta'

type Tab = 'requisicoes' | 'separacao' | 'despachos' | 'comprovantes'

const TABS: { key: Tab; label: string }[] = [
  { key: 'requisicoes', label: 'Requisições' },
  { key: 'separacao', label: 'Separação' },
  { key: 'despachos', label: 'Despachos' },
  { key: 'comprovantes', label: 'Comprovantes' },
]

export default function LogisticaPage() {
  const [tab, setTab] = useState<Tab>('requisicoes')

  const [requisitions, setRequisitions] = useState<SupplyRequisition[]>([])
  const [pickLists, setPickLists] = useState<PickList[]>([])
  const [dispatches, setDispatches] = useState<Dispatch[]>([])
  const [proofs, setProofs] = useState<ProofOfDelivery[]>([])
  const [discrepancies, setDiscrepancies] = useState<DispatchDiscrepancy[]>([])

  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [materials, setMaterials] = useState<MaterialOption[]>([])
  const [warehouses, setWarehouses] = useState<WarehouseOption[]>([])
  const [stockItems, setStockItems] = useState<StockItemOption[]>([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  const [builderOpen, setBuilderOpen] = useState(false)
  const [dispatchFormOpen, setDispatchFormOpen] = useState(false)
  const [deliveringDispatch, setDeliveringDispatch] = useState<Dispatch | null>(null)

  const reloadRequisitions = useCallback(async () => {
    const data = await apiFetch<Listish<SupplyRequisition>>(LOGISTICS_ENDPOINTS.requisitions)
    setRequisitions(unwrap(data))
  }, [])

  const reloadPickLists = useCallback(async () => {
    const data = await apiFetch<Listish<PickList>>(LOGISTICS_ENDPOINTS.pickLists)
    setPickLists(unwrap(data))
  }, [])

  const reloadDispatches = useCallback(async () => {
    const data = await apiFetch<Listish<Dispatch>>(LOGISTICS_ENDPOINTS.dispatches)
    setDispatches(unwrap(data))
  }, [])

  const reloadProofs = useCallback(async () => {
    const [pods, discs] = await Promise.all([
      apiFetch<Listish<ProofOfDelivery>>(LOGISTICS_ENDPOINTS.proofs),
      apiFetch<Listish<DispatchDiscrepancy>>(LOGISTICS_ENDPOINTS.discrepancies),
    ])
    setProofs(unwrap(pods))
    setDiscrepancies(unwrap(discs))
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const [facs, mats, whs, stocks] = await Promise.all([
        apiFetch<Listish<FacilityOption>>(LOGISTICS_ENDPOINTS.facilities),
        apiFetch<Listish<MaterialOption>>(LOGISTICS_ENDPOINTS.materials),
        apiFetch<Listish<WarehouseOption>>(LOGISTICS_ENDPOINTS.warehouses),
        apiFetch<Listish<StockItemOption>>(LOGISTICS_ENDPOINTS.stockItems),
      ])
      setFacilities(unwrap(facs))
      setMaterials(unwrap(mats))
      setWarehouses(unwrap(whs))
      setStockItems(unwrap(stocks))
      await Promise.all([reloadRequisitions(), reloadPickLists(), reloadDispatches(), reloadProofs()])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [reloadRequisitions, reloadPickLists, reloadDispatches, reloadProofs])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const handleRequisitionAction = useCallback(
    async (req: SupplyRequisition, action: RequisitionAction) => {
      setBusyId(req.id)
      try {
        if (action === 'createPick') {
          await apiFetch(LOGISTICS_ENDPOINTS.pickLists, {
            method: 'POST',
            body: JSON.stringify({ requisition: req.id }),
          })
          await Promise.all([reloadPickLists(), reloadRequisitions()])
          setTab('separacao')
        } else {
          await apiFetch(`${LOGISTICS_ENDPOINTS.requisitions}${req.id}/${action}/`, { method: 'POST' })
          await reloadRequisitions()
        }
      } catch {
        setError(true)
      } finally {
        setBusyId(null)
      }
    },
    [reloadPickLists, reloadRequisitions]
  )

  const handleShip = useCallback(
    async (dispatch: Dispatch) => {
      setBusyId(dispatch.id)
      try {
        await apiFetch(`${LOGISTICS_ENDPOINTS.dispatches}${dispatch.id}/ship/`, { method: 'POST' })
        await reloadDispatches()
      } catch {
        setError(true)
      } finally {
        setBusyId(null)
      }
    },
    [reloadDispatches]
  )

  const pickedPickLists = useMemo(() => pickLists.filter((pl) => pl.status === 'picked'), [pickLists])

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Logística de suprimentos</h1>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Requisição → separação → despacho → entrega, com manifesto, assinatura e GPS.
          </p>
        </div>
        <div className="flex gap-2">
          {tab === 'requisicoes' && (
            <button
              type="button"
              onClick={() => setBuilderOpen(true)}
              className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              + Nova requisição
            </button>
          )}
          {tab === 'despachos' && (
            <button
              type="button"
              onClick={() => setDispatchFormOpen(true)}
              className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              + Novo despacho
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-white" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              tab === t.key
                ? 'border-neu-brand text-neu-brand'
                : 'border-transparent text-neu-inkMuted hover:text-neu-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar a logística."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && tab === 'requisicoes' && (
        <>
          {requisitions.length === 0 ? (
            <SectionState
              title="Nenhuma requisição ainda."
              detail='Clique em "+ Nova requisição" para uma unidade solicitar suprimentos.'
            />
          ) : (
            <RequisitionList
              requisitions={requisitions}
              facilities={facilities}
              materials={materials}
              busyId={busyId}
              onAction={handleRequisitionAction}
            />
          )}
        </>
      )}

      {!loading && !error && tab === 'separacao' && (
        <>
          {pickLists.length === 0 ? (
            <SectionState
              title="Nenhuma lista de separação."
              detail='Aprove uma requisição e use "Criar separação" para gerar a lista de picking.'
            />
          ) : (
            <div className="space-y-4">
              {pickLists.map((pl) => (
                <PickPanel
                  key={pl.id}
                  pickList={pl}
                  materials={materials}
                  stockItems={stockItems}
                  warehouses={warehouses}
                  onPicked={(updated) =>
                    setPickLists((current) => current.map((p) => (p.id === updated.id ? updated : p)))
                  }
                />
              ))}
            </div>
          )}
        </>
      )}

      {!loading && !error && tab === 'despachos' && (
        <>
          {dispatches.length === 0 ? (
            <SectionState
              title="Nenhum despacho ainda."
              detail='Separe uma lista e use "+ Novo despacho" para gerar o manifesto.'
            />
          ) : (
            <DispatchList
              dispatches={dispatches}
              warehouses={warehouses}
              busyId={busyId}
              onShip={handleShip}
              onDeliver={setDeliveringDispatch}
            />
          )}
        </>
      )}

      {!loading && !error && tab === 'comprovantes' && (
        <>
          {proofs.length === 0 ? (
            <SectionState
              title="Nenhum comprovante de entrega."
              detail="Os comprovantes (assinatura, GPS e divergências) aparecem aqui após cada entrega."
            />
          ) : (
            <PodViewer
              proofs={proofs}
              dispatches={dispatches}
              discrepancies={discrepancies}
              materials={materials}
            />
          )}
        </>
      )}

      <RequisitionBuilder
        open={builderOpen}
        facilities={facilities}
        materials={materials}
        onClose={() => setBuilderOpen(false)}
        onCreated={() => {
          setBuilderOpen(false)
          reloadRequisitions()
        }}
      />

      <DispatchForm
        open={dispatchFormOpen}
        pickLists={pickedPickLists}
        warehouses={warehouses}
        onClose={() => setDispatchFormOpen(false)}
        onCreated={() => {
          setDispatchFormOpen(false)
          reloadDispatches()
        }}
      />

      {deliveringDispatch && (
        <DeliveryModal
          open
          dispatch={deliveringDispatch}
          materials={materials}
          onClose={() => setDeliveringDispatch(null)}
          onDelivered={() => {
            setDeliveringDispatch(null)
            reloadDispatches()
            reloadProofs()
          }}
        />
      )}
    </PageShell>
  )
}
