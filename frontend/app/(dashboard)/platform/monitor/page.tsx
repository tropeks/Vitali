'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { RefreshCw, CheckCircle, AlertCircle, Activity } from 'lucide-react'
import { PageShell, KpiTile, SectionState, StatusBadge } from '@/components/shared'

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

// ─── Tenant card ──────────────────────────────────────────────────────────────

function TenantCard({ tenant }: { tenant: TenantStat }) {
  const showRate =
    tenant.show_rate_30d !== null ? `${Math.round((tenant.show_rate_30d ?? 0) * 100)}%` : '—'
  const pixConversion =
    tenant.pix_charges_month > 0
      ? `${Math.round((tenant.pix_paid_month / tenant.pix_charges_month) * 100)}%`
      : '—'
  const pixHint =
    tenant.pix_charges_month > 0
      ? `${tenant.pix_paid_month}/${tenant.pix_charges_month}`
      : undefined

  return (
    <section
      className={`rounded-lg border bg-white ${
        tenant.error ? 'border-red-200' : 'border-slate-200'
      }`}
    >
      <div className="border-b border-slate-100 px-4 py-3 flex items-start justify-between gap-2">
        <div>
          <p className="text-base font-semibold text-slate-900">{tenant.name}</p>
          <p className="text-xs font-mono text-slate-500">{tenant.schema}</p>
        </div>
        {tenant.error && (
          <StatusBadge
            meta={{
              label: 'Erro',
              badgeClass: 'bg-red-100 text-red-700 border-red-200',
            }}
          />
        )}
      </div>
      <div className="p-4">
        {tenant.error ? (
          <SectionState title="Erro ao carregar tenant" detail={tenant.error} tone="critical" />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <KpiTile label="Consultas hoje" value={tenant.appointments_today} />
            <KpiTile label="Consultas (7d)" value={tenant.appointments_week} />
            <KpiTile label="Comparecimento (30d)" value={showRate} />
            <KpiTile label="Pacientes ativos (30d)" value={tenant.active_patients_30d} />
            <KpiTile label="Total de pacientes" value={tenant.total_patients} />
            <KpiTile label="Conversão PIX (mês)" value={pixConversion} hint={pixHint} />
          </div>
        )}
      </div>
    </section>
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

  useEffect(() => {
    fetchData()
    timerRef.current = setInterval(fetchData, REFRESH_INTERVAL_S * 1000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchData])

  useEffect(() => {
    const t = setInterval(() => {
      setCountdown((c) => (c > 0 ? c - 1 : REFRESH_INTERVAL_S))
    }, 1000)
    return () => clearInterval(t)
  }, [])

  const isStale = lastFetch && Date.now() - lastFetch.getTime() > 120_000

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Monitor do Piloto</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            KPIs comportamentais e saúde do sistema — atualização automática a cada{' '}
            {REFRESH_INTERVAL_S}s
          </p>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          {lastFetch && (
            <p className={`text-xs ${isStale ? 'text-amber-700 font-semibold' : 'text-slate-500'}`}>
              {isStale ? 'Dados desatualizados · ' : ''}
              Atualizado {lastFetch.toLocaleTimeString('pt-BR')} · próxima em {countdown}s
            </p>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3 py-2 border border-slate-200 bg-white hover:bg-slate-50 rounded-lg text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Atualizar
          </button>
        </div>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar dados do piloto"
          detail={error}
          tone="critical"
          action={
            <button
              onClick={fetchData}
              className="inline-flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-semibold"
            >
              Tentar novamente
            </button>
          }
        />
      )}

      {data?.system && (
        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="px-4 py-3 flex flex-wrap items-center gap-5 text-sm">
            <div className="flex items-center gap-2">
              <Activity size={15} className="text-slate-500" />
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Sistema
              </span>
            </div>
            <div className="flex items-center gap-2">
              {data.system.db_ok ? (
                <CheckCircle size={14} className="text-green-600" />
              ) : (
                <AlertCircle size={14} className="text-red-600" />
              )}
              <span className={data.system.db_ok ? 'text-green-800' : 'text-red-700'}>
                DB {data.system.db_ok ? `ok — ${data.system.db_latency_ms}ms` : 'erro'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {data.system.cache_ok ? (
                <CheckCircle size={14} className="text-green-600" />
              ) : (
                <AlertCircle size={14} className="text-red-600" />
              )}
              <span className={data.system.cache_ok ? 'text-green-800' : 'text-red-700'}>
                Cache {data.system.cache_ok ? 'ok' : 'erro'}
              </span>
            </div>
            <div className="text-slate-500 text-xs ml-auto">
              {data.system.tenant_count} tenant{data.system.tenant_count !== 1 ? 's' : ''} ativos
            </div>
          </div>
        </section>
      )}

      {loading && !data && (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="rounded-lg border border-slate-200 bg-white h-40 animate-pulse"
            />
          ))}
        </div>
      )}

      {data?.tenants && (
        <div className="space-y-4">
          {data.tenants.length === 0 ? (
            <SectionState
              title="Nenhum tenant encontrado."
              detail="Aguarde o provisionamento ou verifique o backend de plataforma."
            />
          ) : (
            data.tenants.map((tenant) => <TenantCard key={tenant.schema} tenant={tenant} />)
          )}
        </div>
      )}

      {data?.generated_at && (
        <p className="text-xs text-slate-500 text-right">
          Gerado em {new Date(data.generated_at).toLocaleString('pt-BR')}
        </p>
      )}
    </PageShell>
  )
}
