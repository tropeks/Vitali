'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
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
  A1: 'bg-red-100 text-red-700', A2: 'bg-red-100 text-red-700', A3: 'bg-red-100 text-red-700',
  B1: 'bg-orange-100 text-orange-700', B2: 'bg-orange-100 text-orange-700',
  C1: 'bg-yellow-100 text-yellow-700', C2: 'bg-yellow-100 text-yellow-700',
  C3: 'bg-yellow-100 text-yellow-700', C4: 'bg-yellow-100 text-yellow-700',
  C5: 'bg-yellow-100 text-yellow-700',
}

const CONTROLLED_OPTIONS = ['none','A1','A2','A3','B1','B2','C1','C2','C3','C4','C5']

type Drug = {
  id: string
  name: string
  generic_name: string
  anvisa_code: string
  barcode: string
  dosage_form: string
  concentration: string
  unit_of_measure: string
  controlled_class: string
  controlled_class_display: string
  is_controlled: boolean
  is_active: boolean
  notes: string
  created_at: string
  updated_at: string
}

export default function DrugDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [drug, setDrug] = useState<Drug | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Partial<Drug>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const token = getAccessToken()
    fetch(`/api/v1/pharmacy/drugs/${id}/`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => { setDrug(d); setForm(d) })
      .finally(() => setLoading(false))
  }, [id])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const token = getAccessToken()
      const res = await fetch(`/api/v1/pharmacy/drugs/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(form),
      })
      if (!res.ok) { setError(extractError(await res.json())); return }
      const updated = await res.json()
      setDrug(updated)
      setForm(updated)
      setEditing(false)
    } finally { setSaving(false) }
  }

  const handleDeactivate = async () => {
    if (!confirm('Desativar este medicamento?')) return
    const token = getAccessToken()
    const res = await fetch(`/api/v1/pharmacy/drugs/${id}/`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.ok || res.status === 204) router.push('/farmacia/catalog')
  }

  if (loading) return <p className="text-sm text-gray-500">Carregando...</p>
  if (!drug) return <p className="text-sm text-red-600">Medicamento não encontrado.</p>

  const field = (label: string, value: string | undefined, mono = false) => (
    <div key={label}>
      <p className="text-xs font-medium text-gray-500 mb-0.5">{label}</p>
      <p className={`text-sm text-gray-900 ${mono ? 'font-mono' : ''}`}>{value || '—'}</p>
    </div>
  )

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-start justify-between">
        <div>
          <button
            onClick={() => router.push('/farmacia/catalog')}
            className="text-sm text-gray-500 hover:text-gray-700 mb-2 flex items-center gap-1"
          >
            ← Catálogo
          </button>
          <h1 className="text-xl font-semibold text-gray-900">{drug.name}</h1>
          <div className="flex items-center gap-2 mt-1">
            {drug.controlled_class !== 'none' && (
              <span className={`px-2 py-0.5 text-xs font-mono font-semibold rounded ${CONTROLLED_BADGE[drug.controlled_class] || 'bg-gray-100 text-gray-600'}`}>
                {drug.controlled_class_display}
              </span>
            )}
            {!drug.is_active && (
              <span className="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-500">Inativo</span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {!editing ? (
            <>
              <button
                onClick={() => setEditing(true)}
                className="px-4 py-2 text-sm font-medium text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100"
              >
                Editar
              </button>
              {drug.is_active && (
                <button
                  onClick={handleDeactivate}
                  className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100"
                >
                  Desativar
                </button>
              )}
            </>
          ) : (
            <>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Salvando...' : 'Salvar'}
              </button>
              <button
                onClick={() => { setEditing(false); setForm(drug) }}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
              >
                Cancelar
              </button>
            </>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="bg-white border border-gray-200 rounded-xl p-6">
        {!editing ? (
          <div className="grid grid-cols-2 gap-6">
            {field('Nome comercial', drug.name)}
            {field('Nome genérico', drug.generic_name)}
            {field('Forma farmacêutica', drug.dosage_form)}
            {field('Concentração', drug.concentration)}
            {field('Unidade de medida', drug.unit_of_measure)}
            {field('Código ANVISA', drug.anvisa_code, true)}
            {field('Código de barras', drug.barcode, true)}
            {field('Observações', drug.notes)}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-0.5">Última atualização</p>
              <p className="text-sm text-gray-500">{new Date(drug.updated_at).toLocaleDateString('pt-BR')}</p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Nome comercial *', key: 'name' },
              { label: 'Nome genérico', key: 'generic_name' },
              { label: 'Forma farmacêutica', key: 'dosage_form' },
              { label: 'Concentração', key: 'concentration' },
              { label: 'Unidade de medida', key: 'unit_of_measure' },
              { label: 'Código ANVISA', key: 'anvisa_code' },
              { label: 'Código de barras', key: 'barcode' },
            ].map(({ label, key }) => (
              <div key={key}>
                <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
                <input
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                  value={(form as any)[key] ?? ''}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                />
              </div>
            ))}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Classe controlada</label>
              <select
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                value={form.controlled_class ?? 'none'}
                onChange={e => setForm(f => ({ ...f, controlled_class: e.target.value }))}
              >
                <option value="none">Não controlado</option>
                {CONTROLLED_OPTIONS.filter(c => c !== 'none').map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-gray-600 mb-1">Observações</label>
              <textarea
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                rows={3}
                value={form.notes ?? ''}
                onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
