'use client'

import { useEffect, useMemo, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults } from '@/lib/admin'

type Order = { id: string; supplier_name?: string; status: string; total?: number; expected_date?: string | null; item_count?: number }
const labels: Record<string, string> = { draft: 'Rascunho', sent: 'Enviado', partial: 'Parcial', received: 'Recebido', cancelled: 'Cancelado' }

/** Operational three-way-match cockpit. Matching details remain server-authoritative. */
export default function ProcurementReconciliationPage() {
  const [orders, setOrders] = useState<Order[]>([])
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { void (async () => { try { const data = await apiFetch<unknown>('/api/v1/pharmacy/purchase-orders/?page_size=200'); setOrders(listResults(data as never) as Order[]) } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar a conciliação.')) } finally { setLoading(false) } })() }, [])
  const visible = useMemo(() => filter === 'all' ? orders : orders.filter(o => o.status === filter), [filter, orders])
  const pending = orders.filter(o => o.status === 'partial' || o.status === 'sent').length
  return <PageShell variant="operational">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold text-neu-ink">Conciliação de compras</h1><p className="mt-1 text-sm text-neu-inkSoft">Visão operacional do pedido, recebimento e validação para pagamento.</p></div><select aria-label="Filtrar pedidos" className="neu-input max-w-48" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">Todos ({orders.length})</option><option value="sent">Aguardando recebimento</option><option value="partial">Recebimento parcial</option><option value="received">Recebidos</option></select></div>
    <div className="grid gap-3 sm:grid-cols-3"><Kpi label="Pendências" value={pending} tone="warning"/><Kpi label="Recebidos" value={orders.filter(o => o.status === 'received').length} tone="success"/><Kpi label="Pedidos" value={orders.length} /></div>
    {error && <SectionState title="Conciliação indisponível" detail={error} tone="critical"/>}
    {loading ? <p className="text-sm text-neu-inkMuted">Carregando…</p> : visible.length === 0 ? <SectionState title="Nenhum pedido encontrado" detail="Ajuste o filtro ou crie uma ordem de compra." tone="success"/> : <div className="overflow-x-auto rounded-xl border border-white bg-neu-panel shadow-neu-panel"><table className="w-full text-sm"><thead><tr className="border-b border-neu-app text-left text-xs uppercase tracking-wide text-neu-inkMuted"><th className="px-4 py-3">Fornecedor</th><th className="px-4 py-3">Itens</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Conciliação</th></tr></thead><tbody>{visible.map(o => <tr key={o.id} className="border-b border-neu-app/60"><td className="px-4 py-3 font-medium text-neu-ink">{o.supplier_name ?? 'Fornecedor não informado'}</td><td className="px-4 py-3 text-neu-inkSoft">{o.item_count ?? '—'}</td><td className="px-4 py-3">{labels[o.status] ?? o.status}</td><td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${o.status === 'received' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{o.status === 'received' ? 'Pronto para conferência fiscal' : 'Aguardando 3-way match'}</span></td></tr>)}</tbody></table></div>}
  </PageShell>
}
function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) { return <div className="rounded-xl border border-white bg-neu-panel p-4 shadow-neu-panel"><p className="text-xs uppercase tracking-wide text-neu-inkMuted">{label}</p><p className={`mt-1 text-2xl font-semibold ${tone === 'warning' ? 'text-amber-600' : tone === 'success' ? 'text-emerald-600' : 'text-neu-ink'}`}>{value}</p></div> }
