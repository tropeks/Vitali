'use client'

import { useEffect, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults } from '@/lib/admin'

type Invoice = { id: string; number: string; supplier_name?: string; status: string; total_amount?: string; issued_at?: string }
const statusLabels: Record<string, string> = { pending: 'Pendente', matched: 'Conciliada', mismatch: 'Divergência', approved: 'Aprovada', cancelled: 'Cancelada' }

export default function NFeEntriesPage() {
  const [items, setItems] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  async function load() { try { const data = await apiFetch<unknown>('/api/v1/pharmacy/supplier-invoices/?page_size=200'); setItems(listResults(data as never) as Invoice[]) } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar as entradas.')) } finally { setLoading(false) } }
  useEffect(() => { void load() }, [])
  async function upload(file: File) {
    setUploading(true); setMessage(null)
    const body = new FormData(); body.append('file', file)
    try { await apiFetch('/api/v1/pharmacy/supplier-invoices/import-xml/', { method: 'POST', body }); setMessage('XML recebido e enviado para conferência.'); await load() }
    catch (e) { setMessage(apiErrorMessage(e, 'A importação automática de XML ainda não está habilitada neste ambiente.')) }
    finally { setUploading(false) }
  }
  return <PageShell variant="operational">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold text-neu-ink">Entradas por NF-e</h1><p className="mt-1 text-sm text-neu-inkSoft">Importe XMLs e acompanhe validação, divergências e aprovação antes de lançar no estoque.</p></div><label className="neu-button-primary cursor-pointer"><input className="sr-only" type="file" accept=".xml,text/xml" disabled={uploading} onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f) }} />{uploading ? 'Enviando…' : 'Importar XML'}</label></div>
    {message && <p role="status" className="rounded-lg bg-neu-panel px-4 py-3 text-sm text-neu-inkSoft">{message}</p>}
    {error && <SectionState title="Entradas indisponíveis" detail={error} tone="critical"/>}
    {loading ? <p className="text-sm text-neu-inkMuted">Carregando…</p> : items.length === 0 ? <SectionState title="Nenhuma NF-e pendente" detail="Importe o XML da nota ou configure a captura automática por e-mail/API." tone="success"/> : <div className="overflow-x-auto rounded-xl border border-white bg-neu-panel shadow-neu-panel"><table className="w-full text-sm"><thead><tr className="border-b border-neu-app text-left text-xs uppercase tracking-wide text-neu-inkMuted"><th className="px-4 py-3">NF-e</th><th className="px-4 py-3">Fornecedor</th><th className="px-4 py-3">Total</th><th className="px-4 py-3">Status</th></tr></thead><tbody>{items.map(i => <tr key={i.id} className="border-b border-neu-app/60"><td className="px-4 py-3 font-medium">{i.number}</td><td className="px-4 py-3">{i.supplier_name ?? '—'}</td><td className="px-4 py-3">{i.total_amount ? `R$ ${i.total_amount}` : '—'}</td><td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${i.status === 'mismatch' ? 'bg-red-100 text-red-700' : i.status === 'approved' || i.status === 'matched' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{statusLabels[i.status] ?? i.status}</span></td></tr>)}</tbody></table></div>}
  </PageShell>
}
