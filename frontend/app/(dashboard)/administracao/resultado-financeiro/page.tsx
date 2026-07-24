'use client'

import { useCallback, useEffect, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage } from '@/lib/admin'

// The DRE aggregate action returns decimal STRINGS (never floats). We format
// them character-by-character and NEVER parse currency into a JS number, so no
// float-rounding error can ever be introduced on money.
type Dre = {
  revenue: string
  expense: string
  result: string
  entries: number
  cash_realized_inflow: string
  cash_realized_outflow: string
  cash_realized_net: string
  payables_open: string
}
const money = (value?: string | number) => {
  const raw = String(value ?? '0').trim().replace(',', '.')
  const negative = raw.startsWith('-')
  const [integer = '0', fraction = '00'] = raw.replace('-', '').split('.')
  return `${negative ? '-' : ''}R$ ${integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.')},${fraction.padEnd(2, '0').slice(0, 2)}`
}
const isNegative = (value?: string) => String(value ?? '0').trim().startsWith('-')

export default function FinancialResultPage() {
  const now = new Date(); const [period, setPeriod] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
  const [unit, setUnit] = useState(''); const [costCenter, setCostCenter] = useState(''); const [dre, setDre] = useState<Dre | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { const qs = new URLSearchParams(); if (period) { const [y, m] = period.split('-'); qs.set('start', `${y}-${m}-01`); qs.set('end', `${y}-${m}-${new Date(Number(y), Number(m), 0).getDate()}`) }; if (unit) qs.set('unit', unit); if (costCenter) qs.set('cost_center', costCenter); const response = await apiFetch<Dre>(`/api/v1/billing/accounting/entries/dre/?${qs}`); setDre(response) } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar o resultado financeiro.')) } finally { setLoading(false) } }, [period, unit, costCenter])
  useEffect(() => { void load() }, [load])
  return <PageShell variant="operational"><div><h1 className="text-2xl font-semibold text-neu-ink">DRE e fluxo de caixa</h1><p className="mt-1 text-sm text-neu-inkSoft">Resultado por competência, unidade e centro de custo.</p></div>
    <section className="flex flex-wrap items-end gap-3 rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><label className="text-sm text-neu-inkSoft">Competência<input aria-label="Competência" type="month" className="neu-input mt-1 block" value={period} onChange={e => setPeriod(e.target.value)} /></label><label className="text-sm text-neu-inkSoft">Unidade<input aria-label="Unidade" className="neu-input mt-1 block" placeholder="Todas" value={unit} onChange={e => setUnit(e.target.value)} /></label><label className="text-sm text-neu-inkSoft">Centro de custo<input aria-label="Centro de custo" className="neu-input mt-1 block" placeholder="Todos" value={costCenter} onChange={e => setCostCenter(e.target.value)} /></label><button className="neu-button-secondary" onClick={() => void load()}>Atualizar</button></section>
    {error && <SectionState title="Resultado indisponível" detail={error} tone="critical" />}
    <section className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><h2 className="font-semibold text-neu-ink">Resultado do exercício (DRE)</h2>{loading ? <p className="mt-4 text-sm text-neu-inkMuted">Carregando…</p> : <div className="mt-3 grid gap-3 sm:grid-cols-4"><Kpi label="Receitas" value={money(dre?.revenue)} tone="success" /><Kpi label="Despesas" value={money(dre?.expense)} tone="critical" /><Kpi label="Resultado" value={money(dre?.result)} tone={dre && isNegative(dre.result) ? 'critical' : 'success'} /><Kpi label="Lançamentos" value={String(dre?.entries ?? 0)} /></div>}</section>
    <section className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><h2 className="font-semibold text-neu-ink">Fluxo de caixa realizado</h2>{loading ? <p className="mt-4 text-sm text-neu-inkMuted">Carregando…</p> : <div className="mt-3 grid gap-3 sm:grid-cols-4"><Kpi label="Entradas realizadas" value={money(dre?.cash_realized_inflow)} tone="success" /><Kpi label="Saídas realizadas" value={money(dre?.cash_realized_outflow)} tone="critical" /><Kpi label="Saldo realizado" value={money(dre?.cash_realized_net)} tone={dre && isNegative(dre.cash_realized_net) ? 'critical' : 'success'} /><Kpi label="Contas a pagar em aberto" value={money(dre?.payables_open)} tone="warning" /></div>}</section>
  </PageShell>
}
function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) { return <div className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><p className="text-xs uppercase tracking-wide text-neu-inkMuted">{label}</p><p className={`mt-1 text-xl font-semibold ${tone === 'critical' ? 'text-rose-600' : tone === 'success' ? 'text-emerald-600' : tone === 'warning' ? 'text-amber-600' : 'text-neu-ink'}`}>{value}</p></div> }
