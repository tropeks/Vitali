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

type Material = {
  id: string
  name: string
  category: string
  barcode: string
  unit_of_measure: string
  is_active: boolean
  notes: string
  updated_at: string
}

export default function MaterialDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [material, setMaterial] = useState<Material | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Partial<Material>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const token = getAccessToken()
    fetch(`/api/v1/pharmacy/materials/${id}/`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => { setMaterial(d); setForm(d) })
      .finally(() => setLoading(false))
  }, [id])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const token = getAccessToken()
      if (!token) { setError('Sessão expirada'); setSaving(false); return }
      const res = await fetch(`/api/v1/pharmacy/materials/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(form),
      })
      if (!res.ok) { setError(extractError(await res.json())); return }
      const updated = await res.json()
      setMaterial(updated)
      setForm(updated)
      setEditing(false)
    } finally { setSaving(false) }
  }

  const handleDeactivate = async () => {
    if (!confirm('Desativar este material?')) return
    const token = getAccessToken()
    if (!token) { router.push('/login'); return }
    const res = await fetch(`/api/v1/pharmacy/materials/${id}/`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (res.ok || res.status === 204) router.push('/farmacia/catalog')
  }

  if (loading) return <p className="text-sm text-gray-500">Carregando...</p>
  if (!material) return <p className="text-sm text-red-600">Material não encontrado.</p>

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
          <h1 className="text-xl font-semibold text-gray-900">{material.name}</h1>
          {!material.is_active && (
            <span className="mt-1 inline-block px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-500">Inativo</span>
          )}
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
              {material.is_active && (
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
                onClick={() => { setEditing(false); setForm(material) }}
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
            {[
              ['Nome', material.name],
              ['Categoria', material.category],
              ['Unidade de medida', material.unit_of_measure],
              ['Código de barras', material.barcode],
              ['Observações', material.notes],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-xs font-medium text-gray-500 mb-0.5">{label}</p>
                <p className="text-sm text-gray-900">{value || '—'}</p>
              </div>
            ))}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-0.5">Última atualização</p>
              <p className="text-sm text-gray-500">{new Date(material.updated_at).toLocaleDateString('pt-BR')}</p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {[
              { label: 'Nome *', key: 'name' },
              { label: 'Categoria', key: 'category' },
              { label: 'Unidade de medida', key: 'unit_of_measure' },
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
