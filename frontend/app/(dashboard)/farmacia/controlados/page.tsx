'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ShieldAlert } from 'lucide-react'
import {
  acknowledgeControlledAlert,
  type ControlledAlert,
  type ControlledSignalKind,
  fetchControlledAlerts,
} from '@/lib/controlled'

const KIND_FILTERS: { value: '' | ControlledSignalKind; label: string }[] = [
  { value: '', label: 'Todos' },
  { value: 'refill_too_soon', label: 'Refill cedo' },
  { value: 'multiple_prescribers', label: 'Múltiplos prescritores' },
  { value: 'quantity_escalation', label: 'Escalada' },
]

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

export default function ControladosPage() {
  const [alerts, setAlerts] = useState<ControlledAlert[]>([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [kindFilter, setKindFilter] = useState<'' | ControlledSignalKind>('')
  const [acking, setAcking] = useState<string | null>(null)

  const load = useCallback(async (kind: '' | ControlledSignalKind) => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchControlledAlerts(kind || undefined)
      setAlerts(data.alerts)
      setEnabled(data.controlled_safety_enabled)
    } catch {
      setError('Erro ao carregar os alertas de controlados. Tente novamente.')
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
      await acknowledgeControlledAlert(id)
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
          <h2 className="flex items-center gap-2 text-lg font-semibold text-neu-ink">
            <ShieldAlert size={20} className="text-red-600" />
            Controlados — Diversão
          </h2>
          <p className="text-sm text-neu-inkMuted">
            Padrões anômalos de dispensação de controlados (Portaria 344). Apenas aviso de
            compliance — nunca bloqueou a dispensa.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
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
          O monitoramento de diversão de controlados está desativado para este estabelecimento.
        </div>
      )}

      {loading && <p className="text-sm text-slate-400">Carregando...</p>}

      {!loading && enabled && (
        <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="border-b border-slate-100 bg-neu-panel">
                {['Paciente', 'Medicamento', 'Sinal', 'Quando', ''].map((h, i) => (
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
                  <td colSpan={5} className="px-4 py-10 text-center text-slate-400 text-sm">
                    Nenhum alerta de controlado em aberto.
                  </td>
                </tr>
              )}
              {alerts.map((a) => (
                <tr key={a.id} className="border-b border-slate-50 align-top">
                  <td className="px-4 py-3 font-medium text-neu-ink">{a.patient_name}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    <p>{a.drug}</p>
                    <p className="text-xs text-slate-400 mt-1">Lista {a.controlled_class}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                      {a.signal_kind_display}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">{formatWhen(a.created_at)}</td>
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
