'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CalendarX, PhoneCall } from 'lucide-react'
import {
  acknowledgeNoShowRisk,
  fetchNoShowRisks,
  type NoShowBand,
  type NoShowRisk,
} from '@/lib/no-show'
import { Button, PageShell } from '@/components/shared'

// Mesma semântica de cor de sempre (low=neutro, medium=atenção, high=crítico),
// só que sobre os tokens/recipes neu-* — `attention` mantém a paleta Tailwind
// yellow padrão (mesmo desvio documentado em lib/operational-ui: não existe
// token âmbar no namespace `neu` ainda).
const BAND_STYLES: Record<NoShowBand, string> = {
  low: 'border border-neu-inkMuted/20 bg-neu-inkMuted/10 text-neu-inkSoft',
  medium: 'border border-yellow-200 bg-yellow-50 text-yellow-800',
  high: 'border border-neu-danger/20 bg-neu-danger/10 text-neu-danger',
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
    <PageShell variant="operational">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-neu-ink">
            <CalendarX size={20} className="text-neu-danger" />
            Risco de Falta
          </h2>
          <p className="text-sm text-neu-inkSoft">
            Predição de não comparecimento por agendamento, derivada do histórico do
            paciente. Apenas aviso — nunca bloqueia o agendamento.
          </p>
        </div>
        <div className="flex gap-2">
          {BAND_FILTERS.map((f) => (
            <Button
              key={f.value || 'all'}
              type="button"
              variant={bandFilter === f.value ? 'primary' : 'secondary'}
              onClick={() => setBandFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-neu-danger/10 border border-neu-danger/20 text-neu-danger text-sm rounded-lg px-4 py-3">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {!enabled && !loading && (
        <div className="bg-neu-panel border border-neu-inkMuted/20 text-neu-inkSoft text-sm rounded-lg px-4 py-6 text-center">
          A predição de risco de falta está desativada para este estabelecimento.
        </div>
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && enabled && (
        <div className="bg-neu-panelAlt rounded-xl border border-white shadow-neu-panel overflow-x-auto">
          <table className="w-full text-sm min-w-[760px]">
            <thead>
              <tr className="border-b border-white bg-neu-panel">
                {['Paciente', 'Agendamento', 'Risco', 'Score', 'Ação sugerida', ''].map((h, i) => (
                  <th
                    key={h || `col-${i}`}
                    className="text-left px-4 py-3 text-xs font-medium text-neu-inkSoft uppercase tracking-wide"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {risks.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-neu-inkMuted text-sm">
                    Nenhum risco de falta em aberto.
                  </td>
                </tr>
              )}
              {risks.map((r) => (
                <tr key={r.id} className="border-b border-white align-top">
                  <td className="px-4 py-3">
                    <p className="font-medium text-neu-ink">{r.patient_name}</p>
                    <p className="text-xs text-neu-inkMuted mt-1">{r.professional_name}</p>
                  </td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    <p>{formatWhen(r.appointment_start)}</p>
                    <p className="text-xs text-neu-inkMuted mt-1">{r.appointment_type_display}</p>
                  </td>
                  <td className="px-4 py-3">
                    <BandBadge band={r.band} label={r.band_display} />
                  </td>
                  <td className="px-4 py-3 font-semibold text-neu-ink">{r.score}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {r.suggested_action === 'confirm_active' ? (
                      <span className="inline-flex items-center gap-1">
                        <PhoneCall size={13} /> {r.suggested_action_display}
                      </span>
                    ) : (
                      r.suggested_action_display
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => handleAcknowledge(r.id)}
                      disabled={acking === r.id}
                    >
                      {acking === r.id ? 'Reconhecendo...' : 'Reconhecer'}
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
