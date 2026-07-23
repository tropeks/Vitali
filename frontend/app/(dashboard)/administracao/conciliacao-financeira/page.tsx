'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults } from '@/lib/admin'

type Tx = { id: string; date?: string; description?: string; amount?: number | string; status?: string; suggested_receivable?: string | null }
type Statement = { id: string; filename?: string; period_start?: string; period_end?: string; status?: string; transaction_count?: number }
const statusLabel: Record<string, string> = { unmatched: 'Pendente', review: 'Em revisão', matched: 'Conciliado' }

export default function FinancialReconciliationPage() {
  const [statements, setStatements] = useState<Statement[]>([])
  const [txs, setTxs] = useState<Tx[]>([])
  const [filter, setFilter] = useState('unmatched')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [s, t] = await Promise.all([
        apiFetch<unknown>('/api/v1/billing/bank-transactions/?page_size=200'),
        apiFetch<unknown>(`/api/v1/billing/bank-transactions/?status=${filter}&page_size=200`),
      ])
      setStatements(listResults(s as never) as Statement[]); setTxs(listResults(t as never) as Tx[])
    } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar a conciliação.')) } finally { setLoading(false) }
  }, [filter])
  useEffect(() => { void load() }, [load])
  const kpis = useMemo(() => ({ pending: txs.filter(t => t.status === 'unmatched' || !t.status).length, suggested: txs.filter(t => !!t.suggested_receivable).length, disputed: txs.filter(t => t.status === 'review').length }), [txs])
  const upload = async (file: File) => { setUploading(true); try { const body = new FormData(); body.append('file', file); await apiFetch('/api/v1/billing/bank-statements/import/', { method: 'POST', body }); await load() } catch (e) { setError(apiErrorMessage(e, 'Não foi possível importar o extrato.')) } finally { setUploading(false); if (input.current) input.current.value = '' } }
  const action = async (id: string, operation: 'approve' | 'reject') => { try { if (operation === 'approve') { await apiFetch(`/api/v1/billing/bank-transactions/${id}/match/`, { method: 'POST' }); await apiFetch(`/api/v1/billing/bank-transactions/${id}/approve/`, { method: 'POST' }) } else { await apiFetch(`/api/v1/billing/bank-transactions/${id}/`, { method: 'PATCH', body: JSON.stringify({ status: 'review' }) }) } await load() } catch (e) { setError(apiErrorMessage(e, 'A operação não pôde ser concluída.')) } }
  return <PageShell variant="operational">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold text-neu-ink">Conciliação financeira</h1><p className="mt-1 text-sm text-neu-inkSoft">Importe extratos e confirme recebimentos com rastreabilidade.</p></div><div><input ref={input} type="file" accept=".csv,.ofx" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f) }} /><button type="button" className="neu-button-primary" disabled={uploading} onClick={() => input.current?.click()}>{uploading ? 'Importando…' : 'Importar extrato CSV/OFX'}</button></div></div>
    <div className="grid gap-3 sm:grid-cols-4"><Kpi label="Pendentes" value={kpis.pending} tone="warning"/><Kpi label="Sugestões" value={kpis.suggested}/><Kpi label="Em revisão" value={kpis.disputed} tone="critical"/><Kpi label="Extratos" value={statements.length} tone="success"/></div>
    {error && <SectionState title="Conciliação indisponível" detail={error} tone="critical"/>}
    <section className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><div className="flex items-center justify-between gap-3"><h2 className="font-semibold text-neu-ink">Transações para revisão</h2><select aria-label="Filtrar transações" className="neu-input max-w-48" value={filter} onChange={e => setFilter(e.target.value)}><option value="unmatched">Pendentes</option><option value="review">Em revisão</option><option value="matched">Conciliadas</option></select></div>{loading ? <p className="mt-4 text-sm text-neu-inkMuted">Carregando…</p> : txs.length === 0 ? <SectionState title="Nenhuma transação nesta fila" detail="Novos extratos importados aparecerão aqui." tone="success"/> : <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-neu-app text-left text-xs uppercase tracking-wide text-neu-inkMuted"><th className="px-3 py-2">Data</th><th className="px-3 py-2">Descrição</th><th className="px-3 py-2">Valor</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Ações</th></tr></thead><tbody>{txs.map(t => <tr key={t.id} className="border-b border-neu-app/60"><td className="px-3 py-3">{t.date ? new Date(t.date).toLocaleDateString('pt-BR') : '—'}</td><td className="px-3 py-3 font-medium">{t.description ?? 'Sem descrição'}{t.suggested_receivable && <span className="ml-2 rounded-full bg-blue-100 px-2 py-1 text-xs text-blue-700">Sugestão encontrada</span>}</td><td className="px-3 py-3">R$ {Number(t.amount ?? 0).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</td><td className="px-3 py-3">{statusLabel[t.status ?? 'unmatched'] ?? t.status}</td><td className="px-3 py-3">{(t.status === 'unmatched' || !t.status) && <div className="flex gap-2"><button className="text-emerald-700 hover:underline" onClick={() => void action(t.id, 'approve')}>Aprovar</button><button className="text-rose-700 hover:underline" onClick={() => void action(t.id, 'reject')}>Rejeitar</button></div>}</td></tr>)}</tbody></table></div>}</section>
    <section className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><h2 className="font-semibold text-neu-ink">Extratos importados</h2>{statements.length === 0 ? <p className="mt-3 text-sm text-neu-inkMuted">Nenhum extrato importado.</p> : <ul className="mt-3 divide-y divide-neu-app">{statements.map(s => <li key={s.id} className="flex justify-between py-3 text-sm"><span>{s.filename ?? 'Extrato'} <span className="text-neu-inkMuted">{s.period_start ?? ''} — {s.period_end ?? ''}</span></span><span className="text-neu-inkSoft">{s.transaction_count ?? 0} transações · {s.status ?? 'processado'}</span></li>)}</ul>}</section>
  </PageShell>
}
function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) { return <div className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><p className="text-xs uppercase tracking-wide text-neu-inkMuted">{label}</p><p className={`mt-1 text-2xl font-semibold ${tone === 'warning' ? 'text-amber-600' : tone === 'critical' ? 'text-rose-600' : tone === 'success' ? 'text-emerald-600' : 'text-neu-ink'}`}>{value}</p></div> }
