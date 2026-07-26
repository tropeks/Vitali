'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { TrendingUp, DollarSign, Wallet, Scale, Activity } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState, KpiTile } from '@/components/shared'
import PnlCostBreakdownChart from '@/components/concession/PnlCostBreakdownChart'
import PnlServiceTable from '@/components/concession/PnlServiceTable'
import ConsumptionLedger from '@/components/concession/ConsumptionLedger'
import MaterialCostEditor from '@/components/concession/MaterialCostEditor'
import {
  currentMonthRange,
  formatBRL,
  formatInt,
  unwrap,
  type ContractPnl,
  type FacilityOption,
  type Listish,
} from '@/components/concession/pnlMeta'
import type { ConcessionContract } from '@/components/concession/contractMeta'

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const LABEL_CLASS = 'mb-1 block text-xs font-medium text-slate-700'

type Tab = 'pnl' | 'consumo' | 'custos'

const TABS: { key: Tab; label: string }[] = [
  { key: 'pnl', label: 'P&L' },
  { key: 'consumo', label: 'Consumo' },
  { key: 'custos', label: 'Custos de material' },
]

export default function PnlPage() {
  const [contracts, setContracts] = useState<ConcessionContract[]>([])
  const [facilities, setFacilities] = useState<FacilityOption[]>([])

  const initial = currentMonthRange()
  const [contractId, setContractId] = useState('')
  const [start, setStart] = useState(initial.start)
  const [end, setEnd] = useState(initial.end)
  const [unit, setUnit] = useState('')

  const [pnl, setPnl] = useState<ContractPnl | null>(null)
  const [loadingPnl, setLoadingPnl] = useState(false)
  const [pnlError, setPnlError] = useState(false)

  const [tab, setTab] = useState<Tab>('pnl')

  // Bootstrap: contracts (picker) + facilities (unit filter + name resolution).
  useEffect(() => {
    ;(async () => {
      const [c, f] = await Promise.all([
        apiFetch<Listish<ConcessionContract>>('/api/v1/concession-contracts/').catch(() => []),
        apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/').catch(() => []),
      ])
      setContracts(unwrap(c))
      setFacilities(unwrap(f))
    })()
  }, [])

  const selectedContract = useMemo(
    () => contracts.find((c) => c.id === contractId) ?? null,
    [contracts, contractId]
  )

  // Units offered in the filter are the ones the contract actually covers.
  const contractUnits = useMemo(() => {
    if (!selectedContract) return []
    const ids = new Set(selectedContract.units.map(String))
    return facilities.filter((f) => ids.has(String(f.id)))
  }, [selectedContract, facilities])

  const loadPnl = useCallback(async () => {
    if (!contractId || !start || !end) {
      setPnl(null)
      return
    }
    setLoadingPnl(true)
    setPnlError(false)
    try {
      const params = new URLSearchParams({ start, end })
      if (unit) params.set('unit', unit)
      const data = await apiFetch<ContractPnl>(
        `/api/v1/concession/contracts/${contractId}/pnl/?${params.toString()}`
      )
      setPnl(data)
    } catch {
      setPnlError(true)
      setPnl(null)
    } finally {
      setLoadingPnl(false)
    }
  }, [contractId, start, end, unit])

  useEffect(() => {
    loadPnl()
  }, [loadPnl])

  // Reset the unit filter whenever the contract changes (units are per-contract).
  function onContractChange(id: string) {
    setContractId(id)
    setUnit('')
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center gap-3">
        <TrendingUp className="text-neu-inkSoft" size={26} />
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">P&L da concessão</h1>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Resultado por contrato: receita faturável, custo (consumo, frete, manutenção) e margem,
            com o consumo de material que os sustenta.
          </p>
        </div>
      </div>

      {/* Tab strip */}
      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.key
                ? 'border-neu-brand text-neu-ink'
                : 'border-transparent text-neu-inkMuted hover:text-neu-ink'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'pnl' && (
        <div className="space-y-4">
          {/* Filters */}
          <div className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-4">
            <label className="block">
              <span className={LABEL_CLASS}>Contrato</span>
              <select
                aria-label="Contrato"
                className={SELECT_CLASS}
                value={contractId}
                onChange={(e) => onContractChange(e.target.value)}
              >
                <option value="">Selecione o contrato</option>
                {contracts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} — {c.client_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className={LABEL_CLASS}>Início</span>
              <input
                aria-label="Início do período"
                type="date"
                className={INPUT_CLASS}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label className="block">
              <span className={LABEL_CLASS}>Fim</span>
              <input
                aria-label="Fim do período"
                type="date"
                className={INPUT_CLASS}
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            <label className="block">
              <span className={LABEL_CLASS}>Unidade (opcional)</span>
              <select
                aria-label="Unidade"
                className={SELECT_CLASS}
                value={unit}
                disabled={!selectedContract}
                onChange={(e) => setUnit(e.target.value)}
              >
                <option value="">Todas as unidades</option>
                {contractUnits.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {!contractId && (
            <SectionState
              title="Selecione um contrato para calcular o P&L."
              detail="Escolha o contrato e o período; a apuração é feita automaticamente."
            />
          )}

          {pnlError && (
            <SectionState
              title="Erro ao calcular o P&L."
              detail="Verifique o período informado e tente novamente."
              tone="critical"
            />
          )}

          {loadingPnl && <p className="text-sm text-neu-inkMuted">Calculando...</p>}

          {!loadingPnl && !pnlError && pnl && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <KpiTile
                  label="Receita"
                  value={formatBRL(pnl.revenue)}
                  icon={<DollarSign size={14} />}
                  tone="success"
                />
                <KpiTile
                  label="Custo"
                  value={formatBRL(pnl.cost)}
                  icon={<Wallet size={14} />}
                  tone="attention"
                />
                <KpiTile
                  label="Resultado"
                  value={formatBRL(pnl.result)}
                  icon={<Scale size={14} />}
                  tone={Number(pnl.result) < 0 ? 'critical' : 'success'}
                />
                <KpiTile
                  label="Volume de exames"
                  value={formatInt(pnl.exam_volume)}
                  icon={<Activity size={14} />}
                />
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <section className="rounded-xl border border-slate-200 bg-white p-4 lg:col-span-1">
                  <h2 className="text-sm font-semibold text-slate-900">Composição do custo</h2>
                  <p className="mt-0.5 text-xs text-slate-500">Consumo, frete e manutenção.</p>
                  <div className="mt-2">
                    <PnlCostBreakdownChart breakdown={pnl.cost_breakdown} />
                  </div>
                </section>

                <section className="lg:col-span-2">
                  <h2 className="mb-2 text-sm font-semibold text-slate-900">
                    Rentabilidade por serviço
                  </h2>
                  {pnl.by_service.length === 0 ? (
                    <SectionState
                      title="Nenhum exame no período."
                      detail="Sem consumo registrado para os filtros selecionados."
                    />
                  ) : (
                    <PnlServiceTable rows={pnl.by_service} />
                  )}
                </section>
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'consumo' && <ConsumptionLedger unit={unit || undefined} />}

      {tab === 'custos' && <MaterialCostEditor />}
    </PageShell>
  )
}
