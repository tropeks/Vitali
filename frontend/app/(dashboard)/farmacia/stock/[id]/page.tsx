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
  return 'Erro. Tente novamente.'
}

const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  entry: 'Entrada',
  dispense: 'Dispensação',
  adjustment: 'Ajuste',
  return: 'Devolução',
  expired_write_off: 'Baixa por vencimento',
  transfer: 'Transferência',
}

type StockItem = {
  id: string
  drug: string | null
  drug_name: string | null
  material_name: string | null
  lot_number: string
  expiry_date: string | null
  quantity: string
  min_stock: string
  location: string
  is_expired: boolean
  is_low_stock: boolean
  updated_at: string
}

type Movement = {
  id: string
  movement_type: string
  movement_type_display: string
  quantity: string
  reference: string
  notes: string
  performed_by_name: string | null
  created_at: string
}

export default function StockItemDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const [item, setItem] = useState<StockItem | null>(null)
  const [movements, setMovements] = useState<Movement[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdjust, setShowAdjust] = useState(false)
  const [adjustQty, setAdjustQty] = useState('')
  const [adjustNotes, setAdjustNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const refresh = async () => {
    setLoading(true)
    try {
      const token = getAccessToken()
      const headers = { Authorization: `Bearer ${token}` }
      const [itemRes, mvRes] = await Promise.all([
        fetch(`/api/v1/pharmacy/stock/items/${id}/`, { headers }),
        fetch(`/api/v1/pharmacy/stock/movements/?stock_item=${id}`, { headers }),
      ])
      const itemData = await itemRes.json()
      const mvData = await mvRes.json()
      setItem(itemData)
      setMovements(mvData.results ?? mvData ?? [])
    } finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [id])

  const handleAdjust = async () => {
    setSaving(true)
    setError('')
    try {
      const token = getAccessToken()
      if (!token) { setError('Sessão expirada'); setSaving(false); return }
      const res = await fetch(`/api/v1/pharmacy/stock/items/${id}/adjust/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ quantity: adjustQty, notes: adjustNotes }),
      })
      if (!res.ok) { setError(extractError(await res.json())); return }
      setShowAdjust(false)
      setAdjustQty('')
      setAdjustNotes('')
      await refresh()
    } finally { setSaving(false) }
  }

  if (loading) return <p className="text-sm text-gray-500">Carregando...</p>
  if (!item) return <p className="text-sm text-red-600">Lote não encontrado.</p>

  const itemName = item.drug_name || item.material_name || '—'
  const expiryFmt = item.expiry_date ? new Date(item.expiry_date).toLocaleDateString('pt-BR') : '—'

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-start justify-between">
        <div>
          <button
            onClick={() => router.push('/farmacia/stock')}
            className="text-sm text-gray-500 hover:text-gray-700 mb-2 flex items-center gap-1"
          >
            ← Estoque
          </button>
          <h1 className="text-xl font-semibold text-gray-900">{itemName}</h1>
          <p className="text-sm text-gray-500 mt-0.5">Lote: <span className="font-mono">{item.lot_number || '—'}</span></p>
          <div className="flex gap-2 mt-1">
            {item.is_expired && (
              <span className="px-2 py-0.5 text-xs font-medium rounded bg-red-100 text-red-700">Vencido</span>
            )}
            {item.is_low_stock && !item.is_expired && (
              <span className="px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-700">Estoque baixo</span>
            )}
          </div>
        </div>
        <button
          onClick={() => setShowAdjust(v => !v)}
          className="px-4 py-2 text-sm font-medium text-blue-700 bg-blue-50 rounded-lg hover:bg-blue-100"
        >
          Ajustar estoque
        </button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Quantidade atual', value: item.quantity, highlight: item.is_low_stock },
          { label: 'Estoque mínimo', value: item.min_stock },
          { label: 'Validade', value: expiryFmt, highlight: item.is_expired },
        ].map(({ label, value, highlight }) => (
          <div key={label} className={`bg-white border rounded-xl p-4 ${highlight ? 'border-red-200' : 'border-gray-200'}`}>
            <p className="text-xs font-medium text-gray-500">{label}</p>
            <p className={`text-2xl font-semibold mt-1 ${highlight ? 'text-red-600' : 'text-gray-900'}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Adjust form */}
      {showAdjust && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
          <h3 className="font-medium text-gray-900">Ajuste de estoque</h3>
          <p className="text-sm text-gray-500">Use valores positivos para entradas e negativos para saídas.</p>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Quantidade *</label>
              <input
                type="number"
                step="0.001"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                placeholder="ex: 10 ou -5"
                value={adjustQty}
                onChange={e => setAdjustQty(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Motivo</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                placeholder="ex: Contagem de inventário"
                value={adjustNotes}
                onChange={e => setAdjustNotes(e.target.value)}
              />
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleAdjust}
              disabled={saving || !adjustQty}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Salvando...' : 'Confirmar ajuste'}
            </button>
            <button
              onClick={() => { setShowAdjust(false); setError('') }}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Movement history */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
          <h3 className="text-sm font-medium text-gray-700">Histórico de movimentos</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              {['Data', 'Tipo', 'Quantidade', 'Referência', 'Usuário'].map(h => (
                <th key={h} className="text-left px-4 py-3 font-medium text-gray-600">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {movements.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">Nenhum movimento registrado</td></tr>
            )}
            {movements.map(mv => {
              const qty = parseFloat(mv.quantity)
              return (
                <tr key={mv.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 text-xs">{new Date(mv.created_at).toLocaleDateString('pt-BR')}</td>
                  <td className="px-4 py-3 text-gray-700">{mv.movement_type_display}</td>
                  <td className={`px-4 py-3 font-mono font-semibold ${qty > 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {qty > 0 ? '+' : ''}{mv.quantity}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs font-mono truncate max-w-[120px]">{mv.reference || mv.notes || '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{mv.performed_by_name || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
