'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CalendarX, PhoneCall } from 'lucide-react'
import {
  acknowledgeNoShowRisk,
  fetchNoShowRisks,
  type NoShowBand,
  type NoShowRisk,
} from '@/lib/no-show'

const BAND_STYLES: Record<NoShowBand, string> = {
  low: 'bg-slate-100 text-slate-700',
  medium: 'bg-amber-100 text-amber-800',
  high: 'bg-red-100 text-red-700',
}

const BAND_FILTERS: { value: '' | NoShowBand; label: string }[] = [
  { value: '', label: 'Todos' },
  { value: 'high', label: 'Alto' },
  { value: 'medium', label: 'Médio' },
]

function formatWhen(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

function BandBadge({ band, label }: { band: NoShowBand; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${
        BAND_STYLES[band] ?? BAND_STYLES.low
      }`}
    >
      {label}
    </span>
  )
}

export default function FaltasPage() {
  const [risks, setRisks] = useState<NoShowRisk[]>([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [bandFilter, setBandFilter] = useState<'' | NoShowBand>('')
  const [acking, setAcking] = useState<string | null>(null)

  const load = useCallback(async (band: '' | NoShowBand) => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchNoShowRisks(band || undefined)
      setRisks(data.risks)
      setEnabled(data.no_show_prediction_enabled)
    } catch {
      setError('Erro ao carregar os riscos de falta. Tente novamente.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(bandFilter)
  }, [bandFilter, load])

  async function handleAcknowledge(id: string) {
    setAcking(id)
    try {
      await acknowledgeNoShowRisk(id)
      setRisks((prev) => prev.filter((r) => r.id !== id))
    } catch {
      setError('Erro ao reconhecer o risco. Tente novamente.')
    } finally {
      setAcking(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
            <CalendarX size={20} className="text-red-600" />
            Risco de Falta
          </h2>
          <p className="text-sm text-slate-500">
            Predição de não comparecimento por agendamento, derivada do histórico do
            paciente. Apenas aviso — nunca bloqueia o agendamento.
          </p>
        </div>
        <div className="flex gap-2">
          {BAND_FILTERS.map((f) => (
            <button
              key={f.value || 'all'}
              onClick={() => setBandFilter(f.value)}
              className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                bandFilter === f.value
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
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
        <div className="bg-slate-50 border border-slate-200 text-slate-500 text-sm rounded-lg px-4 py-6 text-center">
          A predição de risco de falta está desativada para este estabelecimento.
        </div>
      )}

      {loading && <p className="text-sm text-slate-400">Carregando...</p>}

      {!loading && enabled && (
        <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Paciente', 'Agendamento', 'Risco', 'Score', 'Ação sugerida', ''].map((h, i) => (
                  <th
                    key={h || `col-${i}`}
                    className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {risks.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-slate-400 text-sm">
                    Nenhum risco de falta em aberto.
                  </td>
                </tr>
              )}
              {risks.map((r) => (
                <tr key={r.id} className="border-b border-slate-50 align-top">
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-900">{r.patient_name}</p>
                    <p className="text-xs text-slate-400 mt-1">{r.professional_name}</p>
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    <p>{formatWhen(r.appointment_start)}</p>
                    <p className="text-xs text-slate-400 mt-1">{r.appointment_type_display}</p>
                  </td>
                  <td className="px-4 py-3">
                    <BandBadge band={r.band} label={r.band_display} />
                  </td>
                  <td className="px-4 py-3 font-semibold text-slate-900">{r.score}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {r.suggested_action === 'confirm_active' ? (
                      <span className="inline-flex items-center gap-1">
                        <PhoneCall size={13} /> {r.suggested_action_display}
                      </span>
                    ) : (
                      r.suggested_action_display
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleAcknowledge(r.id)}
                      disabled={acking === r.id}
                      className="px-3 py-1.5 text-sm font-medium rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                    >
                      {acking === r.id ? 'Reconhecendo...' : 'Reconhecer'}
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
