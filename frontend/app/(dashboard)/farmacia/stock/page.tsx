'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'

function debounce(fn: Function, ms: number) {
  let timer: any
  return (...args: any[]) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms) }
}

function extractError(err: any): string {
  if (typeof err === 'string') return err
  if (err?.detail) return String(err.detail)
  const firstVal = Object.values(err ?? {})[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao salvar. Tente novamente.'
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
}

type Drug = { id: string; name: string; dosage_form: string; concentration: string }

export default function StockPage() {
  const router = useRouter()
  const [items, setItems] = useState<StockItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showEntryForm, setShowEntryForm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [filterLow, setFilterLow] = useState(false)
  const [filterExpiring, setFilterExpiring] = useState(false)

  // Drug search for entry form
  const [drugSearch, setDrugSearch] = useState('')
  const [drugResults, setDrugResults] = useState<Drug[]>([])
  const [loadingDrugs, setLoadingDrugs] = useState(false)
  const [selectedDrug, setSelectedDrug] = useState<Drug | null>(null)

  // Entry form fields
  const [lotNumber, setLotNumber] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [entryQuantity, setEntryQuantity] = useState('')
  const [entryNotes, setEntryNotes] = useState('')

  const fetchStock = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/v1/pharmacy/stock/items/')
      const data = await res.json()
      setItems(data.results ?? data ?? [])
    } finally { setLoading(false) }
  }

  useEffect(() => { fetchStock() }, [])

  const searchDrugs = useCallback(
    debounce(async (q: string) => {
      if (!q.trim()) { setDrugResults([]); return }
      setLoadingDrugs(true)
      try {
        const res = await fetch(`/api/v1/pharmacy/drugs/?search=${encodeURIComponent(q)}`)
        const data = await res.json()
        setDrugResults(data.results ?? data ?? [])
      } finally { setLoadingDrugs(false) }
    }, 300), []
  )

  const handleEntry = async () => {
    if (!selectedDrug || !lotNumber || !entryQuantity) return
    setSaving(true)
    setError('')
    try {
      // 1. Create StockItem (lot) for this drug
      const itemRes = await fetch('/api/v1/pharmacy/stock/items/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          drug: selectedDrug.id,
          lot_number: lotNumber,
          expiry_date: expiryDate || null,
        }),
      })
      if (!itemRes.ok) {
        const err = await itemRes.json()
        setError(extractError(err))
        return
      }
      const stockItem = await itemRes.json()

      // 2. Register the entry movement
      const movRes = await fetch('/api/v1/pharmacy/stock/movements/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stock_item: stockItem.id,
          movement_type: 'entry',
          quantity: entryQuantity,
          notes: entryNotes,
        }),
      })
      if (!movRes.ok) {
        const err = await movRes.json()
        setError(extractError(err))
        return
      }

      // Reset form
      setShowEntryForm(false)
      setSelectedDrug(null)
      setDrugSearch('')
      setDrugResults([])
      setLotNumber('')
      setExpiryDate('')
      setEntryQuantity('')
      setEntryNotes('')
      fetchStock()
    } finally { setSaving(false) }
  }

  const today = new Date().toISOString().slice(0, 10)
  const soonThreshold = new Date(Date.now() + 30 * 86400 * 1000).toISOString().slice(0, 10)

  const filtered = items.filter(item => {
    if (filterLow && !item.is_low_stock) return false
    if (filterExpiring && item.expiry_date && item.expiry_date > soonThreshold) return false
    return true
  })

  const expiryRowClass = (item: StockItem) => {
    if (!item.expiry_date) return ''
    if (item.is_expired) return 'bg-red-50'
    if (item.expiry_date <= soonThreshold) return 'bg-yellow-50'
    return ''
  }

  const expiringCount = items.filter(
    item => item.expiry_date && !item.is_expired && item.expiry_date <= soonThreshold
  ).length
  const lowStockCount = items.filter(item => item.is_low_stock && !item.is_expired).length

  return (
    <div className="space-y-4">
      {/* KPI cards */}
      {!loading && (expiringCount > 0 || lowStockCount > 0) && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
          {expiringCount > 0 && (
            <button
              onClick={() => { setFilterExpiring(true); setFilterLow(false) }}
              className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-left hover:bg-red-100 transition-colors"
            >
              <p className="text-xs font-medium text-red-600 uppercase tracking-wide">Vencendo em 30d</p>
              <p className="text-2xl font-semibold text-red-700 mt-1">{expiringCount}</p>
              <p className="text-xs text-red-500 mt-0.5">lote(s)</p>
            </button>
          )}
          {lowStockCount > 0 && (
            <button
              onClick={() => { setFilterLow(true); setFilterExpiring(false) }}
              className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-left hover:bg-yellow-100 transition-colors"
            >
              <p className="text-xs font-medium text-yellow-700 uppercase tracking-wide">Estoque baixo</p>
              <p className="text-2xl font-semibold text-yellow-700 mt-1">{lowStockCount}</p>
              <p className="text-xs text-yellow-600 mt-0.5">item(s)</p>
            </button>
          )}
        </div>
      )}

      {/* Filters + action */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              checked={filterLow}
              onChange={e => setFilterLow(e.target.checked)}
              className="rounded border-gray-300"
            />
            Estoque baixo
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
            <input
              type="checkbox"
              checked={filterExpiring}
              onChange={e => setFilterExpiring(e.target.checked)}
              className="rounded border-gray-300"
            />
            Vencendo em 30 dias
          </label>
        </div>
        <button
          onClick={() => { setShowEntryForm(true); setError('') }}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
        >
          + Entrada de Estoque
        </button>
      </div>

      {/* Entry form */}
      {showEntryForm && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h3 className="font-medium text-slate-900">Registrar Entrada de Estoque</h3>
          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {/* Drug search */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Medicamento *</label>
            {selectedDrug ? (
              <div className="flex items-center justify-between px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
                <span className="text-sm font-medium text-blue-900">{selectedDrug.name}</span>
                <button
                  onClick={() => { setSelectedDrug(null); setDrugSearch('') }}
                  className="text-xs text-blue-600 hover:underline"
                >
                  Alterar
                </button>
              </div>
            ) : (
              <>
                <input
                  type="text"
                  placeholder="Buscar medicamento por nome..."
                  value={drugSearch}
                  onChange={e => { setDrugSearch(e.target.value); searchDrugs(e.target.value) }}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {loadingDrugs && <p className="text-xs text-slate-400 mt-1">Buscando...</p>}
                {drugResults.length > 0 && (
                  <div className="mt-1 border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
                    {drugResults.slice(0, 6).map(d => (
                      <button
                        key={d.id}
                        onClick={() => { setSelectedDrug(d); setDrugSearch(''); setDrugResults([]) }}
                        className="w-full text-left px-3 py-2 hover:bg-slate-50 text-sm"
                      >
                        <span className="font-medium text-slate-900">{d.name}</span>
                        {(d.dosage_form || d.concentration) && (
                          <span className="text-slate-400 ml-2 text-xs">
                            {[d.dosage_form, d.concentration].filter(Boolean).join(' ')}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Número do lote *</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono"
                placeholder="Ex: LOT2024-001"
                value={lotNumber}
                onChange={e => setLotNumber(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Data de validade</label>
              <input
                type="date"
                min={today}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                value={expiryDate}
                onChange={e => setExpiryDate(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Quantidade *</label>
              <input
                type="number"
                step="0.001"
                min="0.001"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                placeholder="Ex: 100"
                value={entryQuantity}
                onChange={e => setEntryQuantity(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Observações</label>
              <input
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                placeholder="NF, fornecedor..."
                value={entryNotes}
                onChange={e => setEntryNotes(e.target.value)}
              />
            </div>
          </div>

          <div className="flex gap-3 pt-1">
            <button
              onClick={handleEntry}
              disabled={saving || !selectedDrug || !lotNumber || !entryQuantity}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Salvando...' : 'Registrar Entrada'}
            </button>
            <button
              onClick={() => {
                setShowEntryForm(false)
                setSelectedDrug(null)
                setDrugSearch('')
                setDrugResults([])
                setLotNumber('')
                setExpiryDate('')
                setEntryQuantity('')
                setEntryNotes('')
                setError('')
              }}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-900"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {loading && <p className="text-sm text-slate-400">Carregando...</p>}

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              {['Item', 'Lote', 'Vencimento', 'Quantidade', 'Estoque mín.', 'Local', 'Status'].map(h => (
                <th key={h} className="text-left px-4 py-3 font-medium text-gray-600">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center">
                  <p className="text-sm font-medium text-slate-500">Nenhum item de estoque encontrado</p>
                  <p className="text-xs text-slate-400 mt-1">
                    Registre uma entrada de estoque para começar.
                  </p>
                </td>
              </tr>
            )}
            {filtered.map(item => (
              <tr key={item.id} className={`border-b border-gray-50 hover:bg-gray-50 cursor-pointer ${expiryRowClass(item)}`} onClick={() => router.push(`/farmacia/stock/${item.id}`)}>
                <td className="px-4 py-3 font-medium text-gray-900">
                  {item.drug_name ?? item.material_name ?? '—'}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-gray-600">{item.lot_number || '—'}</td>
                <td className="px-4 py-3 text-gray-600">
                  {item.expiry_date
                    ? <span className={
                        item.is_expired ? 'text-red-600 font-medium' :
                        item.expiry_date <= soonThreshold ? 'text-yellow-700 font-medium' : ''
                      }>
                        {item.expiry_date}
                      </span>
                    : '—'}
                </td>
                <td className="px-4 py-3 font-mono text-gray-900">{item.quantity}</td>
                <td className="px-4 py-3 font-mono text-gray-500">{item.min_stock}</td>
                <td className="px-4 py-3 text-gray-600">{item.location || '—'}</td>
                <td className="px-4 py-3">
                  {item.is_expired
                    ? <span className="px-2 py-0.5 text-xs bg-red-100 text-red-700 rounded">Vencido</span>
                    : item.is_low_stock
                    ? <span className="px-2 py-0.5 text-xs bg-yellow-100 text-yellow-700 rounded">Baixo</span>
                    : <span className="px-2 py-0.5 text-xs bg-green-100 text-green-700 rounded">OK</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
