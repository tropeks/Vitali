'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { getAccessToken } from '@/lib/auth'

function extractError(err: any): string {
  if (typeof err === 'string') return err
  if (err?.detail) return String(err.detail)
  const firstVal = Object.values(err ?? {})[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao salvar. Tente novamente.'
}

const CONTROLLED_BADGE: Record<string, string> = {
  none: '',
  A1: 'bg-red-100 text-red-700',
  A2: 'bg-red-100 text-red-700',
  A3: 'bg-red-100 text-red-700',
  B1: 'bg-orange-100 text-orange-700',
  B2: 'bg-orange-100 text-orange-700',
  C1: 'bg-yellow-100 text-yellow-700',
  C2: 'bg-yellow-100 text-yellow-700',
  C3: 'bg-yellow-100 text-yellow-700',
  C4: 'bg-yellow-100 text-yellow-700',
  C5: 'bg-yellow-100 text-yellow-700',
}

type Drug = {
  id: string
  name: string
  generic_name: string
  dosage_form: string
  concentration: string
  controlled_class: string
  controlled_class_display: string
  is_active: boolean
  anvisa_code?: string | null
}

type Material = {
  id: string
  name: string
  category: string
  unit_of_measure: string
  is_active: boolean
}

export default function CatalogPage() {
  const router = useRouter()
  const [tab, setTab] = useState<'drugs' | 'materials'>('drugs')
  const [search, setSearch] = useState('')
  const [drugs, setDrugs] = useState<Drug[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchDrugsNow = useCallback(async (q: string) => {
    setLoading(true)
    try {
      const token = getAccessToken()
      const res = await fetch(`/api/v1/pharmacy/drugs/?search=${encodeURIComponent(q)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setDrugs(data.results ?? data ?? [])
    } finally { setLoading(false) }
  }, [])

  const fetchMaterialsNow = useCallback(async (q: string) => {
    setLoading(true)
    try {
      const token = getAccessToken()
      const res = await fetch(`/api/v1/pharmacy/materials/?search=${encodeURIComponent(q)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setMaterials(data.results ?? data ?? [])
    } finally { setLoading(false) }
  }, [])

  const fetchDrugs = useCallback((q: string) => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => fetchDrugsNow(q), 300)
  }, [fetchDrugsNow])

  const fetchMaterials = useCallback((q: string) => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => fetchMaterialsNow(q), 300)
  }, [fetchMaterialsNow])

  useEffect(() => {
    if (tab === 'drugs') fetchDrugs(search)
    else fetchMaterials(search)
    // search intentionally excluded: tab-switch loads with current search; handleSearch handles keystroke-driven refetch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, fetchDrugs, fetchMaterials])

  const handleSearch = (q: string) => {
    setSearch(q)
    if (tab === 'drugs') fetchDrugs(q)
    else fetchMaterials(q)
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const token = getAccessToken()
      if (!token) { setError('Sessão expirada'); setSaving(false); return }
      const endpoint = tab === 'drugs' ? '/api/v1/pharmacy/drugs/' : '/api/v1/pharmacy/materials/'
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const err = await res.json()
        setError(extractError(err))
        return
      }
      setShowForm(false)
      setForm({})
      if (tab === 'drugs') fetchDrugs(search)
      else fetchMaterials(search)
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {(['drugs', 'materials'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 text-sm rounded-lg font-medium ${
                tab === t ? 'bg-blue-50 text-blue-700' : 'text-[#57606A] hover:bg-[#DFE5EB]'
              }`}
            >
              {t === 'drugs' ? 'Medicamentos' : 'Materiais'}
            </button>
          ))}
        </div>
        <button
          onClick={() => { setShowForm(true); setForm({ controlled_class: 'none', unit_of_measure: 'un' }) }}
          className="px-4 py-2 bg-gradient-to-b from-[#0066A1] to-[#005282] border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] text-white text-sm font-medium rounded-lg hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)]"
        >
          + {tab === 'drugs' ? 'Medicamento' : 'Material'}
        </button>
      </div>

      <input
        type="text"
        placeholder={tab === 'drugs' ? 'Buscar por nome ou nome genérico...' : 'Buscar por nome...'}
        value={search}
        onChange={e => handleSearch(e.target.value)}
        className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />

      {loading && <p className="text-sm text-[#8C959F]">Carregando...</p>}

      {showForm && (
        <div className="bg-[#F4F7FA] border border-slate-200 rounded-lg p-4 space-y-4">
          <h3 className="font-medium text-[#24292F]">
            {tab === 'drugs' ? 'Novo Medicamento' : 'Novo Material'}
          </h3>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#57606A] mb-1">Nome *</label>
              <input
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                value={form.name ?? ''}
                onChange={e => setForm((f: any) => ({ ...f, name: e.target.value }))}
              />
            </div>
            {tab === 'drugs' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-[#57606A] mb-1">Nome genérico</label>
                  <input
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                    value={form.generic_name ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, generic_name: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#57606A] mb-1">Código ANVISA</label>
                  <input
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono"
                    value={form.anvisa_code ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, anvisa_code: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#57606A] mb-1">Forma farmacêutica</label>
                  <input
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                    value={form.dosage_form ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, dosage_form: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#57606A] mb-1">Concentração</label>
                  <input
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                    value={form.concentration ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, concentration: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#57606A] mb-1">Classe controlada</label>
                  <select
                    className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                    value={form.controlled_class ?? 'none'}
                    onChange={e => setForm((f: any) => ({ ...f, controlled_class: e.target.value }))}
                  >
                    <option value="none">Não controlado</option>
                    {['A1','A2','A3','B1','B2','C1','C2','C3','C4','C5'].map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
              </>
            )}
            {tab === 'materials' && (
              <div>
                <label className="block text-xs font-medium text-[#57606A] mb-1">Categoria</label>
                <input
                  className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                  value={form.category ?? ''}
                  onChange={e => setForm((f: any) => ({ ...f, category: e.target.value }))}
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-[#57606A] mb-1">Unidade de medida</label>
              <input
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
                value={form.unit_of_measure ?? 'un'}
                onChange={e => setForm((f: any) => ({ ...f, unit_of_measure: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving || !form.name}
              className="px-4 py-2 bg-gradient-to-b from-[#0066A1] to-[#005282] border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] text-white text-sm font-medium rounded-lg hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] disabled:opacity-50"
            >
              {saving ? 'Salvando...' : 'Salvar'}
            </button>
            <button
              onClick={() => { setShowForm(false); setForm({}) }}
              className="px-4 py-2 text-sm text-[#57606A] hover:text-[#24292F]"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {tab === 'drugs' ? (
        <div className="bg-[#F4F7FA] rounded-lg border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="border-b border-slate-100 bg-[#F4F7FA]">
                {['Medicamento', 'Nome genérico', 'Forma / Concentração', 'Controlado', 'Código ANVISA'].map(h => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-[#57606A]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drugs.length === 0 && !loading && (
                <tr><td colSpan={5} className="px-4 py-3 text-center text-slate-400">Nenhum medicamento encontrado</td></tr>
              )}
              {drugs.map(d => (
                <tr key={d.id} className="border-b border-slate-50 hover:bg-[#F4F7FA] cursor-pointer" onClick={() => router.push(`/farmacia/catalog/drugs/${d.id}`)}>
                  <td className="px-4 py-3 font-medium text-[#24292F] hover:text-[#0066A1]">{d.name}</td>
                  <td className="px-4 py-3 text-[#57606A]">{d.generic_name || '—'}</td>
                  <td className="px-4 py-3 text-[#57606A]">{[d.dosage_form, d.concentration].filter(Boolean).join(' ')|| '—'}</td>
                  <td className="px-4 py-3">
                    {d.controlled_class !== 'none' ? (
                      <span className={`px-2 py-0.5 text-xs font-mono font-semibold rounded ${CONTROLLED_BADGE[d.controlled_class] || 'bg-[#DFE5EB] text-[#57606A]'}`}>
                        {d.controlled_class}
                      </span>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#8C959F]">{d.anvisa_code || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="bg-[#F4F7FA] rounded-lg border border-slate-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-[#F4F7FA]">
                {['Material', 'Categoria', 'Unidade'].map(h => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-[#57606A]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {materials.length === 0 && !loading && (
                <tr><td colSpan={3} className="px-4 py-3 text-center text-slate-400">Nenhum material encontrado</td></tr>
              )}
              {materials.map(m => (
                <tr key={m.id} className="border-b border-slate-50 hover:bg-[#F4F7FA] cursor-pointer" onClick={() => router.push(`/farmacia/catalog/materials/${m.id}`)}>
                  <td className="px-4 py-3 font-medium text-[#24292F] hover:text-[#0066A1]">{m.name}</td>
                  <td className="px-4 py-3 text-[#57606A]">{m.category || '—'}</td>
                  <td className="px-4 py-3 text-[#57606A]">{m.unit_of_measure}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
