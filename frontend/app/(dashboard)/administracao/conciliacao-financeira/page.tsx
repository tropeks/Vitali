'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults } from '@/lib/admin'

type Tx = { id: string; occurred_at?: string; description?: string; amount?: number | string; status?: string; receivable?: string | null }
const statusLabel: Record<string, string> = { unmatched: 'Pendente', review: 'Em revisão', matched: 'Conciliado' }
const formatMoney = (value?: number | string) => { const [integer = '0', fraction = '00'] = String(value ?? '0').replace(',', '.').split('.'); return `${integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.')},${fraction.padEnd(2, '0').slice(0, 2)}` }

export default function FinancialReconciliationPage() {
  const [txs, setTxs] = useState<Tx[]>([])
  const [filter, setFilter] = useState('unmatched')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const t = await apiFetch<unknown>(`/api/v1/billing/bank-transactions/?status=${filter}&page_size=200`)
      setTxs(listResults(t as never) as Tx[])
    } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar a conciliação.')) } finally { setLoading(false) }
  }, [filter])
  useEffect(() => { void load() }, [load])
  const kpis = useMemo(() => ({ pending: txs.filter(t => t.status === 'unmatched' || !t.status).length, suggested: txs.filter(t => !!t.receivable).length, disputed: txs.filter(t => t.status === 'review').length }), [txs])
  const upload = async (file: File) => { setUploading(true); try { const body = new FormData(); body.append('file', file); await apiFetch('/api/v1/billing/bank-statements/import/', { method: 'POST', body }); await load() } catch (e) { setError(apiErrorMessage(e, 'Não foi possível importar o extrato.')) } finally { setUploading(false); if (input.current) input.current.value = '' } }
  const action = async (id: string, operation: 'approve' | 'reject') => { try { if (operation === 'approve') { await apiFetch(`/api/v1/billing/bank-transactions/${id}/match/`, { method: 'POST' }); await apiFetch(`/api/v1/billing/bank-transactions/${id}/approve/`, { method: 'POST' }) } else { await apiFetch(`/api/v1/billing/bank-transactions/${id}/reject/`, { method: 'POST' }) } await load() } catch (e) { setError(apiErrorMessage(e, 'A operação não pôde ser concluída.')) } }
  return <PageShell variant="operational">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold text-neu-ink">Conciliação financeira</h1><p className="mt-1 text-sm text-neu-inkSoft">Importe extratos e confirme recebimentos com rastreabilidade.</p></div><div><input ref={input} type="file" accept=".csv,.ofx" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f) }} /><button type="button" className="neu-button-primary" disabled={uploading} onClick={() => input.current?.click()}>{uploading ? 'Importando…' : 'Importar extrato CSV/OFX'}</button></div></div>
    <div className="grid gap-3 sm:grid-cols-3"><Kpi label="Pendentes" value={kpis.pending} tone="warning"/><Kpi label="Sugestões" value={kpis.suggested}/><Kpi label="Em revisão" value={kpis.disputed} tone="critical"/></div>
    {error && <SectionState title="Conciliação indisponível" detail={error} tone="critical"/>}
    <section className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><div className="flex items-center justify-between gap-3"><h2 className="font-semibold text-neu-ink">Transações para revisão</h2><select aria-label="Filtrar transações" className="neu-input max-w-48" value={filter} onChange={e => setFilter(e.target.value)}><option value="unmatched">Pendentes</option><option value="review">Em revisão</option><option value="matched">Conciliadas</option></select></div>{loading ? <p className="mt-4 text-sm text-neu-inkMuted">Carregando…</p> : txs.length === 0 ? <SectionState title="Nenhuma transação nesta fila" detail="Novos extratos importados aparecerão aqui." tone="success"/> : <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-neu-app text-left text-xs uppercase tracking-wide text-neu-inkMuted"><th className="px-3 py-2">Data</th><th className="px-3 py-2">Descrição</th><th className="px-3 py-2">Valor</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Ações</th></tr></thead><tbody>{txs.map(t => <tr key={t.id} className="border-b border-neu-app/60"><td className="px-3 py-3">{t.occurred_at ? new Date(t.occurred_at).toLocaleDateString('pt-BR') : '—'}</td><td className="px-3 py-3 font-medium">{t.description ?? 'Sem descrição'}{t.receivable && <span className="ml-2 rounded-full bg-blue-100 px-2 py-1 text-xs text-blue-700">Sugestão encontrada</span>}</td><td className="px-3 py-3">R$ {formatMoney(t.amount)}</td><td className="px-3 py-3">{statusLabel[t.status ?? 'unmatched'] ?? t.status}</td><td className="px-3 py-3">{(t.status === 'unmatched' || !t.status) && <div className="flex gap-2"><button className="text-emerald-700 hover:underline" onClick={() => void action(t.id, 'approve')}>Aprovar</button><button className="text-rose-700 hover:underline" onClick={() => void action(t.id, 'reject')}>Rejeitar</button></div>}</td></tr>)}</tbody></table></div>}</section>
  </PageShell>
}
function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) { return <div className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><p className="text-xs uppercase tracking-wide text-neu-inkMuted">{label}</p><p className={`mt-1 text-2xl font-semibold ${tone === 'warning' ? 'text-amber-600' : tone === 'critical' ? 'text-rose-600' : tone === 'success' ? 'text-emerald-600' : 'text-neu-ink'}`}>{value}</p></div> }
