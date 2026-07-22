'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults, type ListResponse } from '@/lib/admin'
import { Button, PageShell, SectionState } from '@/components/shared'

type Kind = 'legal-entities' | 'facilities' | 'units' | 'cost-centers'
interface RecordItem { id: string; code: string; name: string; status: string; legal_name?: string; tax_identifier?: string; legal_entity?: string; facility?: string | null; parent?: string | null }

const KINDS: { key: Kind; label: string; singular: string }[] = [
  { key: 'legal-entities', label: 'Entidades legais', singular: 'entidade legal' },
  { key: 'facilities', label: 'Estabelecimentos', singular: 'estabelecimento' },
  { key: 'units', label: 'Unidades', singular: 'unidade' },
  { key: 'cost-centers', label: 'Centros de custo', singular: 'centro de custo' },
]
const empty = { code: '', name: '', status: 'active', legal_name: '', tax_identifier: '', legal_entity: '', facility: '', parent: '' }

export default function OrganizationPage() {
  const [kind, setKind] = useState<Kind>('legal-entities')
  const [items, setItems] = useState<RecordItem[]>([])
  const [references, setReferences] = useState<Record<Kind, RecordItem[]>>({ 'legal-entities': [], facilities: [], units: [], 'cost-centers': [] })
  const [form, setForm] = useState({ ...empty })
  const [editing, setEditing] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = useMemo(() => KINDS.find((entry) => entry.key === kind)!, [kind])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const entries = await Promise.all(KINDS.map(async ({ key }) => [key, listResults(await apiFetch<ListResponse<RecordItem>>(`/api/v1/organization/${key}/`))] as const))
      const next = Object.fromEntries(entries) as Record<Kind, RecordItem[]>
      setReferences(next); setItems(next[kind])
    } catch (e) { setError(apiErrorMessage(e, 'Não foi possível carregar a estrutura organizacional.')) }
    finally { setLoading(false) }
  }, [kind])
  useEffect(() => { void load() }, [load])

  function beginEdit(item: RecordItem) {
    setEditing(item.id)
    setForm({ ...empty, ...item, facility: item.facility ?? '', parent: item.parent ?? '', legal_name: item.legal_name ?? '', tax_identifier: item.tax_identifier ?? '', legal_entity: item.legal_entity ?? '' })
  }
  function reset() { setEditing(null); setForm({ ...empty }); setError(null) }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setSaving(true); setError(null)
    const payload: Record<string, unknown> = { code: form.code, name: form.name, status: form.status }
    if (kind === 'legal-entities') Object.assign(payload, { legal_name: form.legal_name, tax_identifier: form.tax_identifier })
    if (kind === 'facilities') payload.legal_entity = form.legal_entity
    if (kind === 'units') Object.assign(payload, { facility: form.facility, parent: form.parent || null })
    if (kind === 'cost-centers') Object.assign(payload, { legal_entity: form.legal_entity, facility: form.facility || null, parent: form.parent || null })
    try {
      await apiFetch(`/api/v1/organization/${kind}/${editing ? `${editing}/` : ''}`, { method: editing ? 'PATCH' : 'POST', body: JSON.stringify(payload) })
      reset(); await load()
    } catch (e) { setError(apiErrorMessage(e, `Não foi possível salvar a ${current.singular}.`)) }
    finally { setSaving(false) }
  }
  async function remove(item: RecordItem) {
    if (!window.confirm(`Excluir ${item.name}?`)) return
    try { await apiFetch(`/api/v1/organization/${kind}/${item.id}/`, { method: 'DELETE' }); await load() }
    catch (e) { setError(apiErrorMessage(e, 'Não foi possível excluir o registro.')) }
  }

  return <PageShell variant="operational">
    <div><h1 className="text-2xl font-semibold text-neu-ink">Estrutura organizacional</h1><p className="mt-1 text-sm text-neu-inkSoft">Cadastros mestres do tenant para operação, governança e apropriação de custos.</p></div>
    <div className="flex flex-wrap gap-2" role="tablist">{KINDS.map(entry => <button key={entry.key} role="tab" aria-selected={kind === entry.key} onClick={() => { setKind(entry.key); reset() }} className={`rounded-lg px-3 py-2 text-sm ${kind === entry.key ? 'bg-neu-brand text-white shadow-neu-btn-primary' : 'bg-neu-panel text-neu-inkSoft shadow-neu-panel'}`}>{entry.label}</button>)}</div>
    {error && <SectionState title="A operação não pôde ser concluída" detail={error} tone="critical" />}
    <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
      <section className="overflow-hidden rounded-xl border border-white bg-neu-panel shadow-neu-panel">
        <div className="border-b border-neu-app px-5 py-4"><h2 className="font-semibold text-neu-ink">{current.label}</h2></div>
        {loading ? <p className="p-5 text-sm text-neu-inkMuted">Carregando…</p> : items.length === 0 ? <div className="p-5"><SectionState title="Nenhum registro" detail={`Cadastre a primeira ${current.singular}.`} /></div> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-neu-app/60 text-xs uppercase text-neu-inkMuted"><tr><th className="px-5 py-3">Código</th><th className="px-5 py-3">Nome</th><th className="px-5 py-3">Status</th><th className="px-5 py-3 text-right">Ações</th></tr></thead><tbody>{items.map(item => <tr key={item.id} className="border-t border-neu-app"><td className="px-5 py-3 font-mono text-xs">{item.code}</td><td className="px-5 py-3 font-medium text-neu-ink">{item.name}</td><td className="px-5 py-3">{item.status === 'active' ? 'Ativo' : 'Inativo'}</td><td className="px-5 py-3 text-right"><button onClick={() => beginEdit(item)} className="mr-3 text-neu-brand hover:underline">Editar</button><button onClick={() => void remove(item)} className="text-neu-danger hover:underline">Excluir</button></td></tr>)}</tbody></table></div>}
      </section>
      <form onSubmit={submit} className="space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-neu-panel">
        <h2 className="font-semibold text-neu-ink">{editing ? 'Editar' : 'Nova'} {current.singular}</h2>
        <Field label="Código" value={form.code} onChange={code => setForm(v => ({ ...v, code }))} required />
        <Field label="Nome" value={form.name} onChange={name => setForm(v => ({ ...v, name }))} required />
        {kind === 'legal-entities' && <><Field label="Razão social" value={form.legal_name} onChange={legal_name => setForm(v => ({ ...v, legal_name }))} /><Field label="Identificador fiscal" value={form.tax_identifier} onChange={tax_identifier => setForm(v => ({ ...v, tax_identifier }))} /></>}
        {(kind === 'facilities' || kind === 'cost-centers') && <Select label="Entidade legal" value={form.legal_entity} items={references['legal-entities']} required onChange={legal_entity => setForm(v => ({ ...v, legal_entity }))} />}
        {(kind === 'units' || kind === 'cost-centers') && <Select label="Estabelecimento" value={form.facility} items={references.facilities} required={kind === 'units'} onChange={facility => setForm(v => ({ ...v, facility }))} />}
        {kind === 'units' && <Select label="Unidade superior" value={form.parent} items={references.units.filter(x => x.id !== editing && (!form.facility || x.facility === form.facility))} onChange={parent => setForm(v => ({ ...v, parent }))} />}
        {kind === 'cost-centers' && <Select label="Centro de custo superior" value={form.parent} items={references['cost-centers'].filter(x => x.id !== editing)} onChange={parent => setForm(v => ({ ...v, parent }))} />}
        <Select label="Status" value={form.status} items={[{ id: 'active', name: 'Ativo' }, { id: 'inactive', name: 'Inativo' }] as RecordItem[]} required onChange={status => setForm(v => ({ ...v, status }))} />
        <div className="flex gap-2"><Button disabled={saving}>{saving ? 'Salvando…' : 'Salvar'}</Button>{editing && <Button type="button" variant="secondary" onClick={reset}>Cancelar</Button>}</div>
      </form>
    </div>
  </PageShell>
}

function Field({ label, value, onChange, required = false }: { label: string; value: string; onChange: (v: string) => void; required?: boolean }) { return <label className="block"><span className="neu-label">{label}</span><input className="neu-input" value={value} required={required} onChange={e => onChange(e.target.value)} /></label> }
function Select({ label, value, items, onChange, required = false }: { label: string; value: string; items: RecordItem[]; onChange: (v: string) => void; required?: boolean }) { return <label className="block"><span className="neu-label">{label}</span><select className="neu-input" value={value} required={required} onChange={e => onChange(e.target.value)}><option value="">{required ? 'Selecione…' : 'Nenhum'}</option>{items.map(item => <option key={item.id} value={item.id}>{item.code ? `${item.code} — ` : ''}{item.name}</option>)}</select></label> }
