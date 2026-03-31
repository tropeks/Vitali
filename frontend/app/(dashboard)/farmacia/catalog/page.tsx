'use client'

import { useState, useCallback, useEffect } from 'react'
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

function debounce(fn: Function, ms: number) {
  let timer: any
  return (...args: any[]) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms) }
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

  const fetchDrugs = useCallback(
    debounce(async (q: string) => {
      setLoading(true)
      try {
        const token = getAccessToken()
        const res = await fetch(`/api/v1/pharmacy/drugs/?search=${encodeURIComponent(q)}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        const data = await res.json()
        setDrugs(data.results ?? data ?? [])
      } finally { setLoading(false) }
    }, 300), []
  )

  const fetchMaterials = useCallback(
    debounce(async (q: string) => {
      setLoading(true)
      try {
        const token = getAccessToken()
        const res = await fetch(`/api/v1/pharmacy/materials/?search=${encodeURIComponent(q)}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        const data = await res.json()
        setMaterials(data.results ?? data ?? [])
      } finally { setLoading(false) }
    }, 300), []
  )

  useEffect(() => {
    if (tab === 'drugs') fetchDrugs(search)
    else fetchMaterials(search)
  }, [tab])

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
                tab === t ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {t === 'drugs' ? 'Medicamentos' : 'Materiais'}
            </button>
          ))}
        </div>
        <button
          onClick={() => { setShowForm(true); setForm({ controlled_class: 'none', unit_of_measure: 'un' }) }}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
        >
          + {tab === 'drugs' ? 'Medicamento' : 'Material'}
        </button>
      </div>

      <input
        type="text"
        placeholder={tab === 'drugs' ? 'Buscar por nome ou nome genérico...' : 'Buscar por nome...'}
        value={search}
        onChange={e => handleSearch(e.target.value)}
        className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />

      {loading && <p className="text-sm text-gray-500">Carregando...</p>}

      {showForm && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
          <h3 className="font-medium text-gray-900">
            {tab === 'drugs' ? 'Novo Medicamento' : 'Novo Material'}
          </h3>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Nome *</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                value={form.name ?? ''}
                onChange={e => setForm((f: any) => ({ ...f, name: e.target.value }))}
              />
            </div>
            {tab === 'drugs' && (
              <>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Nome genérico</label>
                  <input
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                    value={form.generic_name ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, generic_name: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Código ANVISA</label>
                  <input
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono"
                    value={form.anvisa_code ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, anvisa_code: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Forma farmacêutica</label>
                  <input
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                    value={form.dosage_form ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, dosage_form: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Concentração</label>
                  <input
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                    value={form.concentration ?? ''}
                    onChange={e => setForm((f: any) => ({ ...f, concentration: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Classe controlada</label>
                  <select
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
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
                <label className="block text-xs font-medium text-gray-600 mb-1">Categoria</label>
                <input
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                  value={form.category ?? ''}
                  onChange={e => setForm((f: any) => ({ ...f, category: e.target.value }))}
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Unidade de medida</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                value={form.unit_of_measure ?? 'un'}
                onChange={e => setForm((f: any) => ({ ...f, unit_of_measure: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving || !form.name}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Salvando...' : 'Salvar'}
            </button>
            <button
              onClick={() => { setShowForm(false); setForm({}) }}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {tab === 'drugs' ? (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                {['Medicamento', 'Nome genérico', 'Forma / Concentração', 'Controlado', 'Código ANVISA'].map(h => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-gray-600">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drugs.length === 0 && !loading && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">Nenhum medicamento encontrado</td></tr>
              )}
              {drugs.map(d => (
                <tr key={d.id} className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer" onClick={() => router.push(`/farmacia/catalog/drugs/${d.id}`)}>
                  <td className="px-4 py-3 font-medium text-gray-900 hover:text-blue-600">{d.name}</td>
                  <td className="px-4 py-3 text-gray-600">{d.generic_name || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{[d.dosage_form, d.concentration].filter(Boolean).join(' ')|| '—'}</td>
                  <td className="px-4 py-3">
                    {d.controlled_class !== 'none' ? (
                      <span className={`px-2 py-0.5 text-xs font-mono font-semibold rounded ${CONTROLLED_BADGE[d.controlled_class] || 'bg-gray-100 text-gray-600'}`}>
                        {d.controlled_class}
                      </span>
                    ) : <span className="text-gray-400">—</span>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">{d.anvisa_code || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                {['Material', 'Categoria', 'Unidade'].map(h => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-gray-600">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {materials.length === 0 && !loading && (
                <tr><td colSpan={3} className="px-4 py-8 text-center text-gray-400">Nenhum material encontrado</td></tr>
              )}
              {materials.map(m => (
                <tr key={m.id} className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer" onClick={() => router.push(`/farmacia/catalog/materials/${m.id}`)}>
                  <td className="px-4 py-3 font-medium text-gray-900 hover:text-blue-600">{m.name}</td>
                  <td className="px-4 py-3 text-gray-600">{m.category || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{m.unit_of_measure}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
