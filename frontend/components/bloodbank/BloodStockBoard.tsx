'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Droplets, PackagePlus, RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { KpiTile, SectionState } from '@/components/shared'
import BloodBagCard from './BloodBagCard'
import BloodBagEntryModal from './BloodBagEntryModal'
import SerologyModal from './SerologyModal'
import {
  ABO_OPTIONS,
  normalizeList,
  RH_OPTIONS,
  summarizeStock,
  type BloodBagDTO,
  type ListResponse,
} from './bloodbank-types'

interface BloodStockBoardProps {
  canManage: boolean
}

const SEROLOGY_FILTERS = [
  { value: '', label: 'Toda a sorologia' },
  { value: 'quarentena', label: 'Em quarentena' },
  { value: 'liberada', label: 'Liberada' },
  { value: 'descartada', label: 'Descartada' },
]

const STOCK_FILTERS = [
  { value: '', label: 'Todo o estoque' },
  { value: 'disponivel', label: 'Disponível' },
  { value: 'reservada', label: 'Reservada' },
  { value: 'transfundida', label: 'Transfundida' },
  { value: 'vencida', label: 'Vencida' },
  { value: 'descartada', label: 'Descartada' },
]

/**
 * Estoque de hemocomponentes — the blood bag board. Consumes GET
 * /api/v1/blood-bags/ with ABO / Rh / serology / stock filters, renders KPIs
 * (disponíveis por ABO/Rh, quarentena, vencidas) and the bags as cards.
 * Entrada de bolsa + triagem sorológica are gated by `canManage`.
 */
export default function BloodStockBoard({ canManage }: BloodStockBoardProps) {
  const [bags, setBags] = useState<BloodBagDTO[]>([])
  const [abo, setAbo] = useState('')
  const [rh, setRh] = useState('')
  const [serology, setSerology] = useState('')
  const [stock, setStock] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [entering, setEntering] = useState(false)
  const [serologyFor, setSerologyFor] = useState<BloodBagDTO | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    const params = new URLSearchParams()
    if (abo) params.set('abo', abo)
    if (rh) params.set('rh_factor', rh)
    if (serology) params.set('serology_status', serology)
    if (stock) params.set('stock_status', stock)
    const qs = params.toString()
    try {
      const data = await apiFetch<ListResponse<BloodBagDTO> | BloodBagDTO[]>(
        `/api/v1/blood-bags/${qs ? `?${qs}` : ''}`
      )
      setBags(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [abo, rh, serology, stock])

  useEffect(() => {
    load()
  }, [load])

  const summary = useMemo(() => summarizeStock(bags), [bags])

  return (
    <div className="space-y-4">
      {/* KPIs */}
      <div
        aria-label="Indicadores de estoque"
        className="grid grid-cols-2 gap-3 sm:grid-cols-4"
      >
        <KpiTile label="Disponíveis" value={summary.disponiveis} tone="success" icon={<Droplets size={13} />} />
        <KpiTile
          label="Em quarentena"
          value={summary.quarentena}
          tone={summary.quarentena > 0 ? 'attention' : 'neutral'}
        />
        <KpiTile
          label="A vencer (7d)"
          value={summary.aVencer}
          tone={summary.aVencer > 0 ? 'attention' : 'neutral'}
        />
        <KpiTile
          label="Vencidas"
          value={summary.vencidas}
          tone={summary.vencidas > 0 ? 'critical' : 'neutral'}
        />
      </div>

      {/* Disponíveis por ABO/Rh */}
      <div
        aria-label="Disponíveis por tipo sanguíneo"
        className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-neu-panel p-3"
      >
        {ABO_OPTIONS.flatMap((a) =>
          RH_OPTIONS.map((r) => {
            const key = `${a.value}${r.value === 'positivo' ? '+' : '−'}`
            const count = summary.byAboRh[key] ?? 0
            return (
              <span
                key={key}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${
                  count > 0
                    ? 'border-red-200 bg-red-50 text-red-700'
                    : 'border-slate-200 bg-slate-50 text-slate-400'
                }`}
              >
                {key}
                <span className="tabular-nums">{count}</span>
              </span>
            )
          })
        )}
      </div>

      {/* Toolbar: filters + entrada */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Filtrar por grupo ABO"
            value={abo}
            onChange={(e) => setAbo(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="">Todos os ABO</option>
            {ABO_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Filtrar por fator Rh"
            value={rh}
            onChange={(e) => setRh(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="">Todos os Rh</option>
            {RH_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Filtrar por situação sorológica"
            value={serology}
            onChange={(e) => setSerology(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            {SEROLOGY_FILTERS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Filtrar por situação de estoque"
            value={stock}
            onChange={(e) => setStock(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm"
          >
            {STOCK_FILTERS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {canManage && (
          <button
            type="button"
            onClick={() => setEntering(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <PackagePlus size={15} aria-hidden />
            Entrada de bolsa
          </button>
        )}
      </div>

      {loading ? (
        <SectionState
          title="Carregando estoque de hemocomponentes..."
          detail="Buscando as bolsas de sangue do banco."
        />
      ) : error ? (
        <SectionState
          title="Erro ao carregar o estoque"
          detail="Não foi possível carregar as bolsas de sangue. Tente novamente."
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
      ) : bags.length === 0 ? (
        <SectionState
          title="Nenhuma bolsa no estoque"
          detail="Não há bolsas de sangue para os filtros selecionados."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {bags.map((bag) => (
            <BloodBagCard
              key={bag.id}
              bag={bag}
              canManage={canManage}
              onSerology={setSerologyFor}
            />
          ))}
        </div>
      )}

      {entering && (
        <BloodBagEntryModal
          onClose={() => setEntering(false)}
          onCreated={() => {
            setEntering(false)
            load()
          }}
        />
      )}
      {serologyFor && (
        <SerologyModal
          bagId={serologyFor.id}
          bagIdentifier={serologyFor.identifier}
          onClose={() => setSerologyFor(null)}
          onDone={() => {
            setSerologyFor(null)
            load()
          }}
        />
      )}
    </div>
  )
}
