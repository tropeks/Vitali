'use client'

import { useCallback, useEffect, useState } from 'react'
import { Activity, AlertTriangle, HeartPulse } from 'lucide-react'
import {
  acknowledgeDeteriorationAlert,
  type DeteriorationAlert,
  type DeteriorationBand,
  fetchDeteriorationAlerts,
  PARAM_LABELS,
} from '@/lib/deterioration'
import Button from '@/components/shared/Button'
import PageShell from '@/components/shared/PageShell'

// Band → badge styling. Higher band = more alarming colour. low_medium is the
// RCP single-parameter "red score" (urgent ward review).
const BAND_STYLES: Record<DeteriorationBand, string> = {
  low: 'bg-slate-100 text-slate-700',
  low_medium: 'bg-amber-100 text-amber-800',
  medium: 'bg-orange-100 text-orange-800',
  high: 'bg-red-100 text-red-700',
}

function BandBadge({ band, label }: { band: DeteriorationBand; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${
        BAND_STYLES[band] ?? BAND_STYLES.low
      }`}
    >
      <HeartPulse size={12} />
      {label}
    </span>
  )
}

/** Render the contributing parameters (sub-score > 0) as compact chips. */
function Contributors({ breakdown }: { breakdown: Record<string, number> }) {
  const items = Object.entries(breakdown).filter(([, pts]) => pts > 0)
  if (items.length === 0) {
    return <span className="text-neu-inkMuted">—</span>
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map(([param, pts]) => (
        <span
          key={param}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-neu-input text-neu-inkSoft text-xs shadow-neu-inset"
        >
          {PARAM_LABELS[param] ?? param}
          <span className="font-semibold text-neu-ink">+{pts}</span>
        </span>
      ))}
    </div>
  )
}

export default function DeterioracaoPage() {
  const [alerts, setAlerts] = useState<DeteriorationAlert[]>([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [acking, setAcking] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchDeteriorationAlerts()
      setAlerts(data.alerts)
      setEnabled(data.deterioration_safety_enabled)
    } catch {
      setError('Erro ao carregar os alertas de deterioração. Tente novamente.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleAcknowledge(id: string) {
    setAcking(id)
    try {
      await acknowledgeDeteriorationAlert(id)
      // Acknowledged alerts leave the open early-warning list.
      setAlerts((prev) => prev.filter((a) => a.id !== id))
    } catch {
      setError('Erro ao reconhecer o alerta. Tente novamente.')
    } finally {
      setAcking(null)
    }
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-neu-ink">
            <Activity size={20} className="text-red-600" />
            Deterioração Clínica (NEWS2)
          </h2>
          <p className="text-sm text-neu-inkSoft">
            Alerta precoce de deterioração pelo escore NEWS2 (Royal College of Physicians).
            Apenas aviso/escalonamento — nunca bloqueia o registro de sinais vitais.
          </p>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {!enabled && !loading && (
        <div className="neu-panel text-sm text-neu-inkSoft text-center py-6">
          O alerta de deterioração clínica está desativado para este estabelecimento.
        </div>
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && enabled && (
        <div className="bg-neu-panel rounded-xl border border-white shadow-neu-panel overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="border-b border-white bg-neu-input">
                {['Paciente', 'NEWS2', 'Banda', 'Parâmetros', 'Resposta clínica', ''].map(
                  (h, i) => (
                    <th
                      key={h || `col-${i}`}
                      className="text-left px-4 py-3 text-xs font-medium text-neu-inkSoft uppercase tracking-wide"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {alerts.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-neu-inkMuted text-sm">
                    Nenhum alerta de deterioração em aberto.
                  </td>
                </tr>
              )}
              {alerts.map((a) => (
                <tr key={a.id} className="border-b border-neu-app/60 align-top">
                  <td className="px-4 py-3">
                    <p className="font-medium text-neu-ink">{a.patient_name}</p>
                    {a.spo2_scale === 2 && (
                      <p className="text-xs text-neu-inkMuted mt-1">SpO2 Escala 2</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-lg font-bold text-neu-ink">{a.score}</span>
                  </td>
                  <td className="px-4 py-3">
                    <BandBadge band={a.band} label={a.band_display} />
                  </td>
                  <td className="px-4 py-3">
                    <Contributors breakdown={a.breakdown} />
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft max-w-md">{a.message}</td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="secondary"
                      onClick={() => handleAcknowledge(a.id)}
                      disabled={acking === a.id}
                    >
                      {acking === a.id ? 'Reconhecendo...' : 'Reconhecer'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  )
}
