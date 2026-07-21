'use client'

import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, Gauge } from 'lucide-react'
import {
  fetchWedgeTelemetry,
  type WedgeTelemetry,
  type WedgeTelemetryPayload,
} from '@/lib/wedge-telemetry'
import { PageShell, Badge } from '@/components/shared'

const WEDGE_LABELS: Record<string, string> = {
  no_show_prediction: 'Risco de Falta',
  stockout_safety: 'Risco de Ruptura',
  deterioration_safety: 'Deterioração Clínica',
  dose_safety: 'Segurança de Dose',
  allergy_safety: 'Alergia / Interação',
  glosa_safety: 'Prevenção de Glosa',
  controlled_safety: 'Controlados (Desvio)',
}

function wedgeLabel(key: string): string {
  return WEDGE_LABELS[key] ?? key
}

function formatOverrideRate(rate: number | null): string {
  if (rate === null) return '—'
  return `${(rate * 100).toFixed(0)}%`
}

function EnabledBadge({ enabled }: { enabled: boolean }) {
  return <Badge variant={enabled ? 'success' : 'neutral'}>{enabled ? 'Ativo' : 'Inativo'}</Badge>
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-xs font-medium text-neu-inkSoft uppercase tracking-wide">{label}</p>
      <p className="text-lg font-semibold text-neu-ink">{value}</p>
    </div>
  )
}

function WedgeCard({ wedge }: { wedge: WedgeTelemetry }) {
  const outcomes = wedge.flywheel.outcome_counts
  return (
    <div className="neu-panel space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 font-semibold text-neu-ink">
          <Activity size={16} className="text-neu-brand" />
          {wedgeLabel(wedge.key)}
        </h3>
        <EnabledBadge enabled={wedge.enabled} />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Metric label="Alertas" value={wedge.alert_count} />
        <Metric label="Reconhecidos" value={wedge.acknowledged_count} />
        <Metric label="Taxa override" value={formatOverrideRate(wedge.override_rate)} />
      </div>

      <div className="pt-3 border-t border-slate-100">
        <p className="flex items-center gap-1.5 text-xs font-medium text-neu-inkSoft uppercase tracking-wide mb-2">
          <Gauge size={13} /> Flywheel
        </p>
        {outcomes === null ? (
          <p className="text-sm text-neu-inkMuted">Sem rótulo de desfecho para esta cunha.</p>
        ) : Object.keys(outcomes).length === 0 ? (
          <p className="text-sm text-neu-inkMuted">Nenhum desfecho registrado.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {Object.entries(outcomes).map(([outcome, count]) => (
              <li key={outcome}>
                <Badge variant="neutral" className="gap-1.5">
                  <span className="font-medium">{outcome}</span>
                  <span className="text-neu-ink font-semibold">{count}</span>
                </Badge>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-neu-inkMuted mt-2">
          {wedge.flywheel.graded_count} eventos gradados · motor {wedge.engine}
        </p>
      </div>
    </div>
  )
}

export default function WedgeTelemetryPage() {
  const [payload, setPayload] = useState<WedgeTelemetryPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetchWedgeTelemetry()
      .then((data) => {
        if (!cancelled) setPayload(data)
      })
      .catch(() => {
        if (!cancelled) setError('Erro ao carregar a telemetria das cunhas. Tente novamente.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <PageShell variant="operational">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-neu-ink">
          <Gauge size={20} className="text-neu-brand" />
          Telemetria das Cunhas
        </h2>
        <p className="text-sm text-neu-inkMuted">
          Métricas operacionais por cunha determinística (alertas, reconhecimentos, taxa de
          override e flywheel). Apenas observabilidade — não reexecuta nenhum motor.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-neu-danger/10 border border-neu-danger/20 text-neu-danger text-sm rounded-lg px-4 py-3">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {loading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3" data-testid="telemetry-skeleton">
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="neu-panel animate-pulse h-48" />
          ))}
        </div>
      )}

      {!loading && !error && payload && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {payload.wedges.map((w) => (
            <WedgeCard key={w.key} wedge={w} />
          ))}
        </div>
      )}
    </PageShell>
  )
}
