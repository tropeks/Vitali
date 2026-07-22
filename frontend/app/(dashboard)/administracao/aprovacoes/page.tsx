'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults, type ListResponse } from '@/lib/admin'

interface Step { id: string; sequence: number; permission_required: string; status: string; decision_note: string; decided_at: string | null }
interface Approval { id: string; workflow_key: string; reference_type: string; reference_id: string; title: string; context: Record<string, unknown>; status: 'pending' | 'approved' | 'rejected' | 'cancelled'; requested_by: string; created_at: string; steps: Step[] }
type Action = 'approve' | 'reject' | 'cancel'

export default function ApprovalsPage() {
  const [items, setItems] = useState<Approval[]>([])
  const [filter, setFilter] = useState('pending')
  const [selected, setSelected] = useState<{ item: Approval; action: Action } | null>(null)
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { setItems(listResults(await apiFetch<ListResponse<Approval>>('/api/v1/governance/approvals/'))) } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar as aprovações.')) } finally { setLoading(false) } }, [])
  useEffect(() => { void load() }, [load])
  async function decide() { if (!selected) return; setSaving(true); setError(null); try { await apiFetch(`/api/v1/governance/approvals/${selected.item.id}/${selected.action}/`, { method: 'POST', body: JSON.stringify({ note }) }); setSelected(null); setNote(''); await load() } catch (e) { setError(apiErrorMessage(e, 'Não foi possível registrar a decisão.')); setSelected(null) } finally { setSaving(false) } }
  const visible = items.filter(item => filter === 'all' || item.status === filter)
  return <PageShell variant="operational">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold text-neu-ink">Aprovações e alçadas</h1><p className="mt-1 text-sm text-neu-inkSoft">Fila maker-checker com decisões auditáveis e etapas sequenciais.</p></div><select aria-label="Filtrar aprovações" className="neu-input max-w-44" value={filter} onChange={e => setFilter(e.target.value)}><option value="pending">Pendentes</option><option value="approved">Aprovadas</option><option value="rejected">Rejeitadas</option><option value="cancelled">Canceladas</option><option value="all">Todas</option></select></div>
    {error && <SectionState title="A operação não pôde ser concluída" detail={error} tone="critical" />}
    {loading ? <p className="text-sm text-neu-inkMuted">Carregando…</p> : visible.length === 0 ? <SectionState title="Nenhuma solicitação" detail="Não há aprovações com este status." tone="success" /> : <div className="grid gap-4">{visible.map(item => <article key={item.id} className="rounded-xl border border-white bg-neu-panel p-5 shadow-neu-panel"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-neu-brand">{item.workflow_key}</p><h2 className="mt-1 font-semibold text-neu-ink">{item.title}</h2><p className="mt-1 text-xs text-neu-inkSoft">{item.reference_type} · {item.reference_id} · {new Date(item.created_at).toLocaleString('pt-BR')}</p></div><span className="rounded-full bg-neu-app px-3 py-1 text-xs font-semibold">{statusLabel(item.status)}</span></div><ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{item.steps.map(step => <li key={step.id} className="rounded-lg border border-neu-app bg-neu-input p-3 text-xs"><p className="font-semibold text-neu-ink">Etapa {step.sequence}</p><p className="mt-1 text-neu-inkSoft">{step.permission_required}</p><p className="mt-1 font-medium">{statusLabel(step.status)}</p></li>)}</ol>{item.status === 'pending' && <div className="mt-4 flex flex-wrap gap-2"><Button onClick={() => setSelected({ item, action: 'approve' })}>Aprovar</Button><Button variant="danger" onClick={() => setSelected({ item, action: 'reject' })}>Rejeitar</Button><Button variant="secondary" onClick={() => setSelected({ item, action: 'cancel' })}>Cancelar solicitação</Button></div>}</article>)}</div>}
    {selected && <div role="dialog" aria-modal="true" aria-labelledby="decision-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><div className="w-full max-w-lg rounded-xl border border-white bg-neu-panel p-6 shadow-neu-panel"><h2 id="decision-title" className="text-lg font-semibold text-neu-ink">{actionLabel(selected.action)}</h2><p className="mt-1 text-sm text-neu-inkSoft">{selected.item.title}</p><label className="mt-4 block"><span className="neu-label">Nota da decisão</span><textarea autoFocus className="neu-input min-h-24" value={note} onChange={e => setNote(e.target.value)} placeholder="Registre o fundamento da decisão" /></label><div className="mt-5 flex justify-end gap-2"><Button variant="secondary" onClick={() => { setSelected(null); setNote('') }}>Voltar</Button><Button variant={selected.action === 'reject' ? 'danger' : 'primary'} disabled={saving} onClick={() => void decide()}>{saving ? 'Registrando…' : 'Confirmar'}</Button></div></div></div>}
  </PageShell>
}
function statusLabel(status: string) { return ({ pending: 'Pendente', approved: 'Aprovada', rejected: 'Rejeitada', cancelled: 'Cancelada' } as Record<string, string>)[status] ?? status }
function actionLabel(action: Action) { return ({ approve: 'Aprovar solicitação', reject: 'Rejeitar solicitação', cancel: 'Cancelar solicitação' })[action] }
