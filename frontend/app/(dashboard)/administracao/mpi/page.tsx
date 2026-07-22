'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import PatientAutocomplete, { type PatientOption } from '@/components/patients/PatientAutocomplete'
import { Button, PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults, type ListResponse } from '@/lib/admin'

interface Candidate { id: string; patient_a: string; patient_b: string; score: number | string; reasons: string[] | Record<string, unknown>; status: 'open' | 'confirmed' | 'dismissed'; review_notes: string; created_at: string }

export default function MPIPage() {
  const [items, setItems] = useState<Candidate[]>([])
  const [patient, setPatient] = useState<PatientOption | null>(null)
  const [status, setStatus] = useState('open')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => { setLoading(true); setError(null); try { const data = await apiFetch<ListResponse<Candidate>>('/api/v1/mpi/duplicate-candidates/'); setItems(listResults(data)) } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar a fila MPI.')) } finally { setLoading(false) } }, [])
  useEffect(() => { void load() }, [load])
  async function detect() { if (!patient) return; setBusy('detect'); setError(null); try { await apiFetch('/api/v1/mpi/duplicate-candidates/detect/', { method: 'POST', body: JSON.stringify({ patient: patient.id }) }); await load() } catch (e) { setError(apiErrorMessage(e, 'Não foi possível executar a detecção.')) } finally { setBusy(null) } }
  async function review(item: Candidate, action: 'confirm' | 'dismiss') { setBusy(item.id); setError(null); try { await apiFetch(`/api/v1/mpi/duplicate-candidates/${item.id}/${action}/`, { method: 'POST', body: JSON.stringify({ notes: notes[item.id] ?? '' }) }); await load() } catch (e) { setError(apiErrorMessage(e, 'Não foi possível registrar a revisão.')) } finally { setBusy(null) } }
  const visible = items.filter(item => status === 'all' || item.status === status)
  return <PageShell variant="operational">
    <div><h1 className="text-2xl font-semibold text-neu-ink">Identidade de pacientes (MPI)</h1><p className="mt-1 text-sm text-neu-inkSoft">Revisão humana de possíveis duplicidades. A confirmação não realiza merge automático.</p></div>
    {error && <SectionState title="A operação não pôde ser concluída" detail={error} tone="critical" />}
    <section className="rounded-xl border border-white bg-neu-panel p-5 shadow-neu-panel"><h2 className="mb-3 font-semibold text-neu-ink">Detectar para um paciente</h2><div className="flex flex-col gap-3 md:flex-row md:items-end"><div className="flex-1"><PatientAutocomplete value={patient} onChange={setPatient} /></div><Button disabled={!patient || busy === 'detect'} onClick={() => void detect()}>{busy === 'detect' ? 'Analisando…' : 'Detectar duplicidades'}</Button></div></section>
    <div className="flex items-center justify-between"><h2 className="font-semibold text-neu-ink">Fila de revisão</h2><select aria-label="Filtrar por status" className="neu-input max-w-44" value={status} onChange={e => setStatus(e.target.value)}><option value="open">Em aberto</option><option value="confirmed">Confirmadas</option><option value="dismissed">Dispensadas</option><option value="all">Todas</option></select></div>
    {loading ? <p className="text-sm text-neu-inkMuted">Carregando…</p> : visible.length === 0 ? <SectionState title="Fila vazia" detail="Não há candidatos com este status." tone="success" /> : <div className="grid gap-4">{visible.map(item => <article key={item.id} className="rounded-xl border border-white bg-neu-panel p-5 shadow-neu-panel"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase text-neu-inkMuted">Similaridade {Math.round(Number(item.score) * (Number(item.score) <= 1 ? 100 : 1))}%</p><div className="mt-2 flex items-center gap-2 text-sm"><Link className="font-medium text-neu-brand hover:underline" href={`/patients/${item.patient_a}`}>Paciente A</Link><span>×</span><Link className="font-medium text-neu-brand hover:underline" href={`/patients/${item.patient_b}`}>Paciente B</Link></div><p className="mt-2 text-xs text-neu-inkSoft">Motivos: {Array.isArray(item.reasons) ? item.reasons.join(' · ') : Object.keys(item.reasons).join(' · ') || 'similaridade cadastral'}</p></div><span className="rounded-full bg-neu-app px-3 py-1 text-xs font-semibold">{item.status === 'open' ? 'Em aberto' : item.status === 'confirmed' ? 'Confirmada' : 'Dispensada'}</span></div>{item.status === 'open' && <div className="mt-4 flex flex-col gap-3 md:flex-row"><input aria-label="Notas da revisão" className="neu-input flex-1" placeholder="Justificativa ou observação" value={notes[item.id] ?? ''} onChange={e => setNotes(v => ({ ...v, [item.id]: e.target.value }))} /><Button disabled={busy === item.id} onClick={() => void review(item, 'confirm')}>Confirmar duplicidade</Button><Button disabled={busy === item.id} variant="secondary" onClick={() => void review(item, 'dismiss')}>Dispensar</Button></div>}</article>)}</div>}
  </PageShell>
}
