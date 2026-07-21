'use client'

/**
 * S-132: Platform admin panel — clinic lifecycle.
 *
 * Lists tenants with status tabs (pending / trial / active / …) and a count per
 * bucket so admins can see at a glance which self-serve signups are stuck in
 * PENDING (owner never clicked the welcome link). Each pending row can re-issue
 * the welcome email. Consumes GET/POST /api/v1/platform/tenants/*.
 */

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Mail } from 'lucide-react'
import { PageShell, StatusBadge, SectionState } from '@/components/shared'

// ─── Types ──────────────────────────────────────────────────────────────────

interface TenantRow {
  id: string
  name: string
  slug: string
  cnpj: string | null
  status: string
  trial_ends_at: string | null
  created_at: string | null
  subscription_status: string | null
  plan_name: string | null
  has_billing: boolean
}

interface TenantListResponse {
  counts: Record<string, number>
  results: TenantRow[]
}

// ─── Status → badge mapping (tenant lifecycle is admin-only, mapped locally) ──

const STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  pending: { label: 'Pendente', badgeClass: 'bg-yellow-100 text-yellow-800 border-yellow-200' },
  trial: { label: 'Trial', badgeClass: 'bg-blue-100 text-blue-800 border-blue-200' },
  active: { label: 'Ativo', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  suspended: { label: 'Suspenso', badgeClass: 'bg-orange-100 text-orange-800 border-orange-200' },
  cancelled: { label: 'Cancelado', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' },
}

const TABS: { key: string; label: string }[] = [
  { key: 'all', label: 'Todas' },
  { key: 'pending', label: 'Pendentes' },
  { key: 'trial', label: 'Trial' },
  { key: 'active', label: 'Ativas' },
  { key: 'suspended', label: 'Suspensas' },
  { key: 'cancelled', label: 'Canceladas' },
]

function formatDate(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('pt-BR')
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PlatformTenantsPage() {
  const [data, setData] = useState<TenantListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('all')
  const [resendingId, setResendingId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const fetchData = useCallback(async (statusKey: string) => {
    setLoading(true)
    setError(null)
    try {
      const qs = statusKey && statusKey !== 'all' ? `?status=${statusKey}` : ''
      const r = await fetch(`/api/v1/platform/tenants/${qs}`)
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${r.status}`)
      }
      setData((await r.json()) as TenantListResponse)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData(activeTab)
  }, [fetchData, activeTab])

  async function resendWelcome(tenant: TenantRow) {
    setResendingId(tenant.id)
    setNotice(null)
    try {
      const r = await fetch(`/api/v1/platform/tenants/${tenant.id}/resend-welcome/`, {
        method: 'POST',
      })
      const body = await r.json().catch(() => ({}))
      setNotice(
        r.ok
          ? `E-mail de boas-vindas reenviado para ${body.owner_email ?? tenant.name}.`
          : body.detail ?? 'Falha ao reenviar o e-mail.',
      )
    } catch {
      setNotice('Erro de conexão ao reenviar o e-mail.')
    } finally {
      setResendingId(null)
    }
  }

  const counts = data?.counts ?? {}
  const rows = data?.results ?? []

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Clínicas</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Ciclo de vida dos tenants — cadastro, trial e assinatura.
          </p>
        </div>
        <button
          type="button"
          onClick={() => fetchData(activeTab)}
          className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50"
        >
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          Atualizar
        </button>
      </div>

      {/* Status tabs with counts */}
      <div className="mt-5 flex flex-wrap gap-2">
        {TABS.map((tab) => {
          const count = tab.key === 'all' ? counts.total : counts[tab.key]
          const isActive = activeTab === tab.key
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {tab.label}
              <span
                className={`text-xs font-semibold rounded px-1.5 py-0.5 ${
                  isActive ? 'bg-white/20' : 'bg-slate-100 text-slate-500'
                }`}
              >
                {count ?? 0}
              </span>
            </button>
          )
        })}
      </div>

      {notice && (
        <div className="mt-4">
          <SectionState title="Aviso" detail={notice} tone="neutral" />
        </div>
      )}

      <div className="mt-5">
        {error ? (
          <SectionState title="Erro ao carregar clínicas" detail={error} tone="critical" />
        ) : loading && rows.length === 0 ? (
          <SectionState title="Carregando..." detail="Buscando clínicas." tone="neutral" />
        ) : rows.length === 0 ? (
          <SectionState
            title="Nenhuma clínica"
            detail="Não há clínicas neste status."
            tone="neutral"
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 font-medium">Clínica</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Plano</th>
                  <th className="px-4 py-3 font-medium">Cobrança</th>
                  <th className="px-4 py-3 font-medium">Trial até</th>
                  <th className="px-4 py-3 font-medium">Criada</th>
                  <th className="px-4 py-3 font-medium text-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-4 py-3">
                      <p className="font-medium text-slate-900">{t.name}</p>
                      <p className="text-xs font-mono text-slate-500">{t.slug}</p>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        meta={STATUS_META[t.status] ?? { label: t.status, badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' }}
                      />
                    </td>
                    <td className="px-4 py-3 text-slate-600">{t.plan_name ?? '—'}</td>
                    <td className="px-4 py-3">
                      {t.has_billing ? (
                        <span className="text-green-700">Ativa</span>
                      ) : (
                        <span className="text-slate-400">Pendente</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{formatDate(t.trial_ends_at)}</td>
                    <td className="px-4 py-3 text-slate-600">{formatDate(t.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      {t.status === 'pending' && (
                        <button
                          type="button"
                          onClick={() => resendWelcome(t)}
                          disabled={resendingId === t.id}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-50 disabled:opacity-50"
                        >
                          <Mail size={13} />
                          {resendingId === t.id ? 'Enviando...' : 'Reenviar convite'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </PageShell>
  )
}
