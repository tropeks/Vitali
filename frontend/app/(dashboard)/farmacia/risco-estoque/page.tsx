'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CalendarClock, PackageX } from 'lucide-react'
import {
  acknowledgeStockAlert,
  fetchStockRisk,
  type StockAlertKind,
  type StockRiskAlert,
} from '@/lib/stock-risk'

const KIND_LABELS: Record<string, string> = {
  stockout_risk: 'Risco de ruptura',
  expiry_waste: 'Desperdício por validade',
}

const KIND_FILTERS: { value: '' | StockAlertKind; label: string }[] = [
  { value: '', label: 'Todos' },
  { value: 'stockout_risk', label: 'Ruptura' },
  { value: 'expiry_waste', label: 'Validade' },
]

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00')
  return d.toLocaleDateString('pt-BR')
}

function KindBadge({ kind }: { kind: string }) {
  const isStockout = kind === 'stockout_risk'
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${
        isStockout ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
      }`}
    >
      {isStockout ? <PackageX size={12} /> : <CalendarClock size={12} />}
      {KIND_LABELS[kind] ?? kind}
    </span>
  )
}

export default function RiscoEstoquePage() {
  const [alerts, setAlerts] = useState<StockRiskAlert[]>([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [kindFilter, setKindFilter] = useState<'' | StockAlertKind>('')
  const [acking, setAcking] = useState<string | null>(null)

  const load = useCallback(async (kind: '' | StockAlertKind) => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchStockRisk(kind || undefined)
      setAlerts(data.alerts)
      setEnabled(data.stockout_safety_enabled)
    } catch {
      setError('Erro ao carregar os alertas de risco. Tente novamente.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(kindFilter)
  }, [kindFilter, load])

  async function handleAcknowledge(id: string) {
    setAcking(id)
    try {
      await acknowledgeStockAlert(id)
      // Acknowledged alerts leave the open risk list.
      setAlerts((prev) => prev.filter((a) => a.id !== id))
    } catch {
      setError('Erro ao reconhecer o alerta. Tente novamente.')
    } finally {
      setAcking(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Risco de Estoque</h2>
          <p className="text-sm text-neu-inkMuted">
            Previsões proativas de ruptura e desperdício por validade. Apenas aviso — nunca
            bloqueia a dispensa.
          </p>
        </div>
        <div className="flex gap-2">
          {KIND_FILTERS.map((f) => (
            <button
              key={f.value || 'all'}
              onClick={() => setKindFilter(f.value)}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                kindFilter === f.value
                  ? 'bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white border-blue-600'
                  : 'bg-neu-panel text-neu-inkSoft border-slate-200 hover:bg-neu-panel'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {!enabled && !loading && (
        <div className="bg-neu-panel border border-slate-200 text-neu-inkMuted text-sm rounded-lg px-4 py-3 text-center">
          A predição de risco de estoque está desativada para este estabelecimento.
        </div>
      )}

      {loading && <p className="text-sm text-slate-400">Carregando...</p>}

      {!loading && enabled && (
        <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="border-b border-slate-100 bg-neu-panel">
                {[
                  'Produto',
                  'Tipo',
                  'Data prevista',
                  'Dias até ruptura',
                  'Desperdício',
                  'Reposição sugerida',
                  '',
                ].map((h, i) => (
                  <th
                    key={h || `col-${i}`}
                    className="text-left px-4 py-3 text-xs font-medium text-neu-inkMuted uppercase tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {alerts.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-400 text-sm">
                    Nenhum alerta de risco em aberto.
                  </td>
                </tr>
              )}
              {alerts.map((a) => (
                <tr key={a.id} className="border-b border-slate-50 align-top">
                  <td className="px-4 py-3">
                    <p className="font-medium text-neu-ink">{a.product_name}</p>
                    <p className="text-xs text-slate-400 mt-1 max-w-md">{a.message}</p>
                  </td>
                  <td className="px-4 py-3">
                    <KindBadge kind={a.kind} />
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">{formatDate(a.predicted_date)}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {a.days_to_stockout ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {a.predicted_waste_qty ?? '—'}
                  </td>
                  <td className="px-4 py-3 font-medium text-neu-ink">
                    {a.suggested_reorder_qty ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleAcknowledge(a.id)}
                      disabled={acking === a.id}
                      className="px-3 py-1.5 text-sm font-medium rounded-lg border border-slate-200 text-neu-inkSoft hover:bg-neu-panel disabled:opacity-50"
                    >
                      {acking === a.id ? 'Reconhecendo...' : 'Reconhecer'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
