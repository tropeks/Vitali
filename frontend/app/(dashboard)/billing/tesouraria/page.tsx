'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults, type ListResponse } from '@/lib/admin'
import CashFlowSummary from '@/components/billing/CashFlowSummary'
import CashFlowTable from '@/components/billing/CashFlowTable'
import type { CashFlowEntry } from '@/components/billing/financeFormat'

const KIND_OPTIONS = [
  { value: '', label: 'Todos os tipos' },
  { value: 'inflow', label: 'Entradas' },
  { value: 'outflow', label: 'Saídas' },
]
const STATUS_OPTIONS = [
  { value: '', label: 'Todos os status' },
  { value: 'forecast', label: 'Previsto' },
  { value: 'realized', label: 'Realizado' },
  { value: 'cancelled', label: 'Cancelado' },
]

export default function TesourariaPage() {
  const now = new Date()
  const [period, setPeriod] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
  const [kind, setKind] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [entries, setEntries] = useState<CashFlowEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // kind/status are server-side filters (DjangoFilterBackend); the period is
      // applied client-side because cash-flow has no date-range filter param.
      const qs = new URLSearchParams()
      if (kind) qs.set('kind', kind)
      if (statusFilter) qs.set('status', statusFilter)
      const query = qs.toString()
      const data = await apiFetch<ListResponse<CashFlowEntry>>(
        `/api/v1/billing/cash-flow/${query ? `?${query}` : ''}`
      )
      setEntries(listResults(data))
    } catch (e) {
      setError(apiErrorMessage(e, 'Não foi possível carregar o fluxo de caixa.'))
    } finally {
      setLoading(false)
    }
  }, [kind, statusFilter])

  useEffect(() => {
    void load()
  }, [load])

  const inPeriod = useMemo(
    () => entries.filter((e) => (period ? (e.due_date ?? '').startsWith(period) : true)),
    [entries, period]
  )

  const totals = useMemo(() => {
    let inflow = 0
    let outflow = 0
    let forecastCount = 0
    for (const e of inPeriod) {
      const amount = Number(e.amount ?? 0)
      if (e.status === 'realized' && e.kind === 'inflow') inflow += amount
      else if (e.status === 'realized' && e.kind === 'outflow') outflow += amount
      if (e.status === 'forecast') forecastCount += 1
    }
    return { inflow, outflow, forecastCount }
  }, [inPeriod])

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Tesouraria</h1>
        <p className="mt-1 text-sm text-neu-inkSoft">
          Fluxo de caixa: entradas, saídas e saldo realizado por período.
        </p>
      </div>

      <section className="flex flex-wrap items-end gap-3 rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel">
        <label className="text-sm text-neu-inkSoft">
          Período
          <input aria-label="Período" type="month" className="neu-input mt-1 block" value={period} onChange={(e) => setPeriod(e.target.value)} />
        </label>
        <label className="text-sm text-neu-inkSoft">
          Tipo
          <select aria-label="Tipo" className="neu-input mt-1 block" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="text-sm text-neu-inkSoft">
          Status
          <select aria-label="Status" className="neu-input mt-1 block" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <button className="neu-button-secondary" onClick={() => void load()}>Atualizar</button>
      </section>

      {error && <SectionState title="Fluxo de caixa indisponível" detail={error} tone="critical" />}

      {loading ? (
        <p className="text-sm text-neu-inkMuted">Carregando…</p>
      ) : (
        <>
          <CashFlowSummary inflow={totals.inflow} outflow={totals.outflow} forecastCount={totals.forecastCount} />
          {!error && inPeriod.length === 0 ? (
            <SectionState
              title="Nenhum lançamento no período."
              detail="Ajuste o período ou os filtros para ver entradas e saídas."
            />
          ) : (
            <CashFlowTable entries={inPeriod} />
          )}
        </>
      )}
    </PageShell>
  )
}
