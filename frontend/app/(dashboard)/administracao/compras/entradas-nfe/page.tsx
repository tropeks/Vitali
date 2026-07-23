'use client'

import { useEffect, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults } from '@/lib/admin'

type InvoiceItem = { id: string; sequence: number; description: string; supplier_code?: string; quantity: string; unit_price: string; ncm?: string; barcode?: string; lot?: string; expires_at?: string; drug?: string | null; material?: string | null }
type Invoice = { id: string; number: string; access_key?: string; supplier_name?: string; issuer_cnpj?: string; recipient_cnpj?: string; status: string; total_amount?: string; issued_at?: string; validation_errors?: string[]; items?: InvoiceItem[] }
const statusLabels: Record<string, string> = { pending: 'Pendente', validated: 'Validada', approved: 'Aprovada', rejected: 'Rejeitada' }

export default function NFeEntriesPage() {
  const [items, setItems] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [selected, setSelected] = useState<Invoice | null>(null)
  const [working, setWorking] = useState(false)
  async function load() { try { const data = await apiFetch<unknown>('/api/v1/pharmacy/nfe-receipts/?page_size=200'); setItems(listResults(data as never) as Invoice[]) } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar as entradas.')) } finally { setLoading(false) } }
  useEffect(() => { void load() }, [])
  async function upload(file: File) {
    setUploading(true); setMessage(null)
    const body = new FormData(); body.append('file', file)
    try { await apiFetch('/api/v1/pharmacy/nfe-receipts/', { method: 'POST', body }); setMessage('XML recebido e enviado para conferência.'); await load() }
    catch (e) { setMessage(apiErrorMessage(e, 'Não foi possível importar o XML.')) }
    finally { setUploading(false) }
  }
  async function approve(invoice: Invoice) {
    setWorking(true); setMessage(null)
    try { const updated = await apiFetch<Invoice>(`/api/v1/pharmacy/nfe-receipts/${invoice.id}/approve/`, { method: 'POST' }); setItems(current => current.map(item => item.id === invoice.id ? updated : item)); setSelected(updated); setMessage('NF-e aprovada e pronta para lançamento no estoque.') }
    catch (e) { setMessage(apiErrorMessage(e, 'Não foi possível aprovar a NF-e.')) }
    finally { setWorking(false) }
  }
  return <PageShell variant="operational">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold text-neu-ink">Entradas por NF-e</h1><p className="mt-1 text-sm text-neu-inkSoft">Importe XMLs e acompanhe validação, divergências e aprovação antes de lançar no estoque.</p></div><label className="neu-button-primary cursor-pointer"><input className="sr-only" type="file" accept=".xml,text/xml" disabled={uploading} onChange={e => { const f = e.target.files?.[0]; if (f) void upload(f) }} />{uploading ? 'Enviando…' : 'Importar XML'}</label></div>
    {message && <p role="status" className="rounded-lg bg-neu-panel px-4 py-3 text-sm text-neu-inkSoft">{message}</p>}
    {error && <SectionState title="Entradas indisponíveis" detail={error} tone="critical"/>}
    {loading ? <p className="text-sm text-neu-inkMuted">Carregando…</p> : items.length === 0 ? <SectionState title="Nenhuma NF-e pendente" detail="Importe o XML da nota ou configure a captura automática por e-mail/API." tone="success"/> : <div className="overflow-x-auto rounded-xl border border-white bg-neu-panel shadow-neu-panel"><table className="w-full text-sm"><thead><tr className="border-b border-neu-app text-left text-xs uppercase tracking-wide text-neu-inkMuted"><th className="px-4 py-3">NF-e</th><th className="px-4 py-3">Fornecedor</th><th className="px-4 py-3">Total</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Ação</th></tr></thead><tbody>{items.map(i => <tr key={i.id} className="border-b border-neu-app/60"><td className="px-4 py-3 font-medium"><button className="text-left text-indigo-700 underline-offset-2 hover:underline" onClick={() => setSelected(i)}>{i.number || i.access_key || 'NF-e'}</button></td><td className="px-4 py-3">{i.supplier_name ?? i.issuer_cnpj ?? '—'}</td><td className="px-4 py-3">{i.total_amount ? `R$ ${i.total_amount}` : '—'}</td><td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${i.status === 'mismatch' ? 'bg-red-100 text-red-700' : i.status === 'approved' || i.status === 'matched' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{statusLabels[i.status] ?? i.status}</span></td><td className="px-4 py-3 text-right"><button className="neu-button-secondary text-xs" onClick={() => setSelected(i)}>Conferir</button></td></tr>)}</tbody></table></div>}
    {selected && <section aria-label="Conferência da NF-e" className="mt-5 rounded-xl border border-white bg-neu-panel p-5 shadow-neu-panel"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-neu-ink">Conferência da NF-e {selected.number || selected.access_key}</h2><p className="text-sm text-neu-inkMuted">Valide itens, quantidades, lotes e mapeamento antes de efetivar a entrada.</p></div><button className="neu-button-secondary text-xs" onClick={() => setSelected(null)}>Fechar</button></div>{selected.validation_errors && selected.validation_errors.length > 0 && <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700"><strong>Divergências fiscais:</strong> {selected.validation_errors.join('; ')}</div>}<div className="mt-4 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-neu-app text-left text-xs uppercase text-neu-inkMuted"><th className="py-2">Item</th><th className="py-2">Código/NCM</th><th className="py-2">Qtd.</th><th className="py-2">Lote/validade</th><th className="py-2">Mapeamento</th></tr></thead><tbody>{(selected.items ?? []).map(item => <tr key={item.id} className="border-b border-neu-app/60"><td className="py-2 pr-3">{item.description}</td><td className="py-2 pr-3">{item.supplier_code || '—'} / {item.ncm || '—'}</td><td className="py-2 pr-3">{item.quantity}</td><td className="py-2 pr-3">{item.lot || '—'}{item.expires_at ? ` · ${item.expires_at}` : ''}</td><td className="py-2"><span className={item.drug || item.material ? 'text-emerald-700' : 'text-amber-700'}>{item.drug || item.material ? 'Mapeado' : 'Pendente — revisar catálogo'}</span></td></tr>)}</tbody></table></div><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><span className="text-xs text-neu-inkMuted">Aprovação parcial fica registrada por item quando disponível no backend.</span><div className="flex gap-2"><button className="neu-button-secondary text-xs" disabled={working || selected.status === 'approved'} onClick={() => setMessage('Devolução registrada como pendência de conferência; efetive pelo módulo de recebimentos.')}>Solicitar devolução</button><button className="neu-button-primary text-xs" disabled={working || selected.status === 'approved'} onClick={() => void approve(selected)}>{working ? 'Aprovando…' : 'Aprovar NF-e'}</button></div></div></section>}
  </PageShell>
}
