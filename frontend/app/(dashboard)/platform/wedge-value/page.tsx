'use client'

import { useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import { RefreshCw, ShieldCheck, Syringe, CalendarClock, PackageOpen } from 'lucide-react'
import { PageShell, KpiTile, SectionState, StatusBadge } from '@/components/shared'

// ─── Types ────────────────────────────────────────────────────────────────────
// Shape mirrors apps/core/views_platform.WedgeValueDashboardView. The `metrics`
// payload is additive-only (apps/core/services/wedge_value); every field is
// optional here so an older snapshot never crashes the page.

interface GlosaMetrics {
  fired?: number
  blocked_count?: number
  blocked_value_brl?: number
  advise_count?: number
  overridden?: number
  override_rate?: number | null
}

interface DoseMetrics {
  fired?: number
  overridden?: number
  override_rate?: number | null
}

interface NoShowMetrics {
  high_risk_flagged?: number
  true_positives?: number
  slots_recovered?: number
}

interface StockoutMetrics {
  alerts?: number
  intercepted?: number
  purchase_orders_created?: number
}

interface OverrideEntry {
  fired?: number
  overridden?: number
  rate?: number | null
}

interface WedgeMetrics {
  window_days?: number
  glosa_safety?: GlosaMetrics
  dose_safety?: DoseMetrics
  no_show_prediction?: NoShowMetrics
  stockout_safety?: StockoutMetrics
  override_rate_by_wedge?: Record<string, OverrideEntry>
  roi_brl?: number
}

interface TenantValue {
  schema: string
  name: string
  snapshot_date?: string
  generated_at?: string
  window_days?: number
  metrics: WedgeMetrics
  error?: string
}

interface Totals {
  roi_brl: number
  glosa_blocked_count: number
  dose_alerts_fired: number
  no_show_slots_recovered: number
  stockout_intercepted: number
  tenant_count: number
}

interface WedgeValuePayload {
  source: 'snapshot' | 'live'
  generated_at: string
  snapshot_date: string
  tenants: TenantValue[]
  totals: Totals
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const brl = (v: number | undefined | null) =>
  (v ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

const pct = (r: number | null | undefined) => (r == null ? '—' : `${Math.round(r * 100)}%`)

const WEDGE_LABELS: Record<string, string> = {
  glosa_safety: 'Glosa',
  dose_safety: 'Dose',
  deterioration: 'Deterioração',
}

// ─── Per-wedge panel ───────────────────────────────────────────────────────────

function WedgePanel({
  icon,
  title,
  children,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
        <span className="text-slate-500">{icon}</span>
        <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

// ─── Tenant card ──────────────────────────────────────────────────────────────

function TenantCard({ tenant }: { tenant: TenantValue }) {
  const m = tenant.metrics ?? {}
  const glosa = m.glosa_safety ?? {}
  const dose = m.dose_safety ?? {}
  const noShow = m.no_show_prediction ?? {}
  const stockout = m.stockout_safety ?? {}
  const overrides = m.override_rate_by_wedge ?? {}

  return (
    <section
      className={`rounded-lg border bg-white ${
        tenant.error ? 'border-red-200' : 'border-slate-200'
      }`}
    >
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div>
          <p className="text-base font-semibold text-slate-900">{tenant.name}</p>
          <p className="font-mono text-xs text-slate-500">{tenant.schema}</p>
        </div>
        <div className="text-right">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">ROI estimado</p>
          <p className="text-lg font-semibold text-green-700">{brl(m.roi_brl)}</p>
        </div>
      </div>

      <div className="space-y-4 p-4">
        {tenant.error ? (
          <SectionState title="Erro ao carregar tenant" detail={tenant.error} tone="critical" />
        ) : (
          <>
            {/* Glosa — R$ bloqueado pelo wedge glosa_safety */}
            <WedgePanel icon={<ShieldCheck size={15} />} title="Glosas bloqueadas (glosa_safety)">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <KpiTile
                  label="R$ bloqueado"
                  value={brl(glosa.blocked_value_brl)}
                  tone="success"
                />
                <KpiTile label="Linhas bloqueadas" value={glosa.blocked_count ?? 0} />
                <KpiTile label="Avisos" value={glosa.advise_count ?? 0} />
                <KpiTile
                  label="Override"
                  value={pct(glosa.override_rate)}
                  hint={`${glosa.overridden ?? 0}/${glosa.fired ?? 0}`}
                />
              </div>
            </WedgePanel>

            {/* Dose — disparados vs ignorados */}
            <WedgePanel icon={<Syringe size={15} />} title="Alertas de dose (dose_safety)">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <KpiTile label="Disparados" value={dose.fired ?? 0} />
                <KpiTile
                  label="Ignorados"
                  value={dose.overridden ?? 0}
                  tone={dose.overridden ? 'attention' : 'neutral'}
                />
                <KpiTile label="Taxa de override" value={pct(dose.override_rate)} />
              </div>
            </WedgePanel>

            {/* No-show — slots recuperados e reagendados */}
            <WedgePanel
              icon={<CalendarClock size={15} />}
              title="No-show recuperado (no_show_prediction)"
            >
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <KpiTile
                  label="Slots reagendados"
                  value={noShow.slots_recovered ?? 0}
                  tone={noShow.slots_recovered ? 'success' : 'neutral'}
                />
                <KpiTile label="Risco alto sinalizado" value={noShow.high_risk_flagged ?? 0} />
                <KpiTile label="Acertos (no-show)" value={noShow.true_positives ?? 0} />
              </div>
            </WedgePanel>

            {/* Stockout — alertas que levaram a PO */}
            <WedgePanel icon={<PackageOpen size={15} />} title="Stockout → compra (stockout_safety)">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <KpiTile label="Alertas de ruptura" value={stockout.alerts ?? 0} />
                <KpiTile
                  label="Interceptados"
                  value={stockout.intercepted ?? 0}
                  tone={stockout.intercepted ? 'success' : 'neutral'}
                />
                <KpiTile label="Pedidos de compra" value={stockout.purchase_orders_created ?? 0} />
              </div>
            </WedgePanel>

            {/* Override rate por tipo de wedge */}
            {Object.keys(overrides).length > 0 && (
              <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Override rate por wedge
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  {Object.entries(overrides).map(([key, o]) => (
                    <div key={key} className="flex items-baseline gap-1.5">
                      <span className="font-medium text-slate-700">
                        {WEDGE_LABELS[key] ?? key}
                      </span>
                      <span className="font-semibold text-slate-900">{pct(o.rate)}</span>
                      <span className="text-xs text-slate-500">
                        ({o.overridden ?? 0}/{o.fired ?? 0})
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function WedgeValuePage() {
  const [data, setData] = useState<WedgeValuePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [live, setLive] = useState(false)

  const fetchData = useCallback(async (forceLive: boolean) => {
    setLoading(true)
    setError(null)
    try {
      const url = forceLive
        ? '/api/v1/platform/wedge-value/?live=1'
        : '/api/v1/platform/wedge-value/'
      const r = await fetch(url)
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${r.status}`)
      }
      const json: WedgeValuePayload = await r.json()
      setData(json)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData(live)
  }, [fetchData, live])

  const totals = data?.totals

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Valor dos Wedges</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            ROI de negócio por wedge por tenant — calculado a partir dos verdicts de IA, atualizado
            diariamente via Celery Beat.
          </p>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          {data && (
            <p className="text-xs text-slate-500">
              {data.source === 'live' ? 'Cálculo ao vivo' : 'Snapshot diário'} ·{' '}
              {new Date(data.generated_at).toLocaleString('pt-BR')}
            </p>
          )}
          <label className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
            <input
              type="checkbox"
              checked={live}
              onChange={(e) => setLive(e.target.checked)}
              className="rounded border-slate-300"
            />
            Ao vivo
          </label>
          <button
            onClick={() => fetchData(live)}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Atualizar
          </button>
        </div>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar métricas de valor"
          detail={error}
          tone="critical"
          action={
            <button
              onClick={() => fetchData(live)}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700"
            >
              Tentar novamente
            </button>
          }
        />
      )}

      {/* Headline totals across all tenants */}
      {totals && (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center gap-2">
            <StatusBadge
              meta={{
                label: data?.source === 'live' ? 'Ao vivo' : 'Snapshot',
                badgeClass:
                  data?.source === 'live'
                    ? 'bg-blue-100 text-blue-700 border-blue-200'
                    : 'bg-slate-100 text-slate-600 border-slate-200',
              }}
            />
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Consolidado · {totals.tenant_count} tenant{totals.tenant_count !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <KpiTile label="R$ glosas bloqueadas" value={brl(totals.roi_brl)} tone="success" />
            <KpiTile label="Linhas bloqueadas" value={totals.glosa_blocked_count} />
            <KpiTile label="Alertas de dose" value={totals.dose_alerts_fired} />
            <KpiTile label="Slots recuperados" value={totals.no_show_slots_recovered} />
            <KpiTile label="Stockouts interceptados" value={totals.stockout_intercepted} />
          </div>
        </section>
      )}

      {loading && !data && (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="h-64 animate-pulse rounded-lg border border-slate-200 bg-white" />
          ))}
        </div>
      )}

      {data?.tenants && (
        <div className="space-y-4">
          {data.tenants.length === 0 ? (
            <SectionState
              title="Nenhum tenant com métricas."
              detail="Aguarde o primeiro snapshot diário ou use o modo ao vivo."
            />
          ) : (
            data.tenants.map((tenant) => <TenantCard key={tenant.schema} tenant={tenant} />)
          )}
        </div>
      )}

      {data?.snapshot_date && (
        <p className="text-right text-xs text-slate-500">
          Janela de cálculo: últimos {data.tenants[0]?.window_days ?? 30} dias · referência{' '}
          {new Date(data.snapshot_date).toLocaleDateString('pt-BR')}
        </p>
      )}
    </PageShell>
  )
}
