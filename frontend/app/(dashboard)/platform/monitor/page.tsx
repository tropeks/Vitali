'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, CheckCircle, AlertCircle, Activity } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface TenantStat {
  schema: string
  name: string
  created_at: string | null
  appointments_today: number
  appointments_week: number
  show_rate_30d: number | null
  active_patients_30d: number
  total_patients: number
  pix_charges_month: number
  pix_paid_month: number
  error?: string
}

interface SystemHealth {
  db_ok: boolean
  db_latency_ms?: number
  db_error?: string
  cache_ok: boolean
  tenant_count: number
}

interface PilotHealth {
  generated_at: string
  tenants: TenantStat[]
  system: SystemHealth
}

// ─── Sparkline ───────────────────────────────────────────────────────────────

function Sparkline({ values, color = '#6366f1' }: { values: number[]; color?: string }) {
  if (values.length < 2) return null
  const max = Math.max(...values, 1)
  const min = Math.min(...values)
  const range = max - min || 1
  const w = 80
  const h = 28
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - ((v - min) / range) * h
    return `${x},${y}`
  })
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// ─── KPI card ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, unit, sparkValues }: {
  label: string
  value: string | number | null
  unit?: string
  sparkValues?: number[]
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col gap-2">
      <p className="text-xs text-slate-500">{label}</p>
      <div className="flex items-end justify-between gap-2">
        <p className="text-2xl font-semibold text-slate-900">
          {value === null || value === undefined ? '—' : value}
          {unit && <span className="text-sm text-slate-400 ml-1">{unit}</span>}
        </p>
        {sparkValues && <Sparkline values={sparkValues} />}
      </div>
    </div>
  )
}

// ─── Tenant row ───────────────────────────────────────────────────────────────

function TenantCard({ tenant }: { tenant: TenantStat }) {
  const showRate = tenant.show_rate_30d !== null
    ? `${Math.round((tenant.show_rate_30d ?? 0) * 100)}%`
    : '—'
  const pixConversion = tenant.pix_charges_month > 0
    ? `${Math.round((tenant.pix_paid_month / tenant.pix_charges_month) * 100)}%`
    : '—'

  return (
    <div className={`bg-white border rounded-xl p-5 space-y-4 ${tenant.error ? 'border-red-200' : 'border-slate-200'}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-slate-900">{tenant.name}</p>
          <p className="text-xs text-slate-400 font-mono">{tenant.schema}</p>
        </div>
        {tenant.error && (
          <span className="text-xs text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full">
            erro
          </span>
        )}
      </div>

      {tenant.error ? (
        <p className="text-xs text-red-600">{tenant.error}</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <KpiCard label="Consultas hoje" value={tenant.appointments_today} />
          <KpiCard label="Consultas (7d)" value={tenant.appointments_week} />
          <KpiCard label="Taxa de comparecimento (30d)" value={showRate} />
          <KpiCard label="Pacientes ativos (30d)" value={tenant.active_patients_30d} />
          <KpiCard label="Total de pacientes" value={tenant.total_patients} />
          <KpiCard
            label="Conversão PIX (mês)"
            value={pixConversion}
            unit={tenant.pix_charges_month > 0 ? `${tenant.pix_paid_month}/${tenant.pix_charges_month}` : undefined}
          />
        </div>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_S = 30

export default function PilotMonitorPage() {
  const [data, setData] = useState<PilotHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<Date | null>(null)
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL_S)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch('/api/v1/platform/pilot-health/')
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${r.status}`)
      }
      const json: PilotHealth = await r.json()
      setData(json)
      setLastFetch(new Date())
      setCountdown(REFRESH_INTERVAL_S)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }, [])

  // Auto-refresh
  useEffect(() => {
    fetchData()
    timerRef.current = setInterval(fetchData, REFRESH_INTERVAL_S * 1000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchData])

  // Countdown ticker
  useEffect(() => {
    const t = setInterval(() => {
      setCountdown((c) => (c > 0 ? c - 1 : REFRESH_INTERVAL_S))
    }, 1000)
    return () => clearInterval(t)
  }, [])

  // Stale threshold: data older than 2 minutes is highlighted
  const isStale = lastFetch && Date.now() - lastFetch.getTime() > 120_000

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Monitor do Piloto</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            KPIs comportamentais e saúde do sistema — atualização automática a cada {REFRESH_INTERVAL_S}s
          </p>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          {lastFetch && (
            <p className={`text-xs ${isStale ? 'text-amber-600 font-medium' : 'text-slate-400'}`}>
              {isStale ? '⚠ Dados desatualizados — ' : ''}
              Atualizado {lastFetch.toLocaleTimeString('pt-BR')} · próxima em {countdown}s
            </p>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 border border-slate-200 rounded-lg text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Atualizar
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {/* System health bar */}
      {data?.system && (
        <div className="bg-white border border-slate-200 rounded-xl px-5 py-4 flex flex-wrap items-center gap-5 text-sm">
          <div className="flex items-center gap-2">
            <Activity size={15} className="text-slate-400" />
            <span className="text-slate-500 text-xs font-medium uppercase tracking-wide">Sistema</span>
          </div>
          <div className="flex items-center gap-2">
            {data.system.db_ok ? (
              <CheckCircle size={14} className="text-green-500" />
            ) : (
              <AlertCircle size={14} className="text-red-500" />
            )}
            <span className={data.system.db_ok ? 'text-green-700' : 'text-red-700'}>
              DB {data.system.db_ok ? `ok — ${data.system.db_latency_ms}ms` : 'erro'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {data.system.cache_ok ? (
              <CheckCircle size={14} className="text-green-500" />
            ) : (
              <AlertCircle size={14} className="text-red-500" />
            )}
            <span className={data.system.cache_ok ? 'text-green-700' : 'text-red-700'}>
              Cache {data.system.cache_ok ? 'ok' : 'erro'}
            </span>
          </div>
          <div className="text-slate-500 text-xs ml-auto">
            {data.system.tenant_count} tenant{data.system.tenant_count !== 1 ? 's' : ''} ativos
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="bg-white border border-slate-200 rounded-xl p-5 h-40 animate-pulse" />
          ))}
        </div>
      )}

      {/* Tenant cards */}
      {data?.tenants && (
        <div className="space-y-4">
          {data.tenants.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-400 text-sm">
              Nenhum tenant encontrado.
            </div>
          ) : (
            data.tenants.map((tenant) => (
              <TenantCard key={tenant.schema} tenant={tenant} />
            ))
          )}
        </div>
      )}

      {/* Generated at */}
      {data?.generated_at && (
        <p className="text-xs text-slate-400 text-right">
          Gerado em {new Date(data.generated_at).toLocaleString('pt-BR')}
        </p>
      )}
    </div>
  )
}
