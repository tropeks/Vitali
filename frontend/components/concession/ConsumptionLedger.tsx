'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  formatBRL,
  formatDateTime,
  unwrap,
  type ConcessionServiceLite,
  type ExamConsumptionRow,
  type FacilityOption,
  type Listish,
} from './pnlMeta'

/**
 * ConsumptionLedger — append-only exam-consumption ledger (B0-T4). The rows
 * carry bare FKs only, so unit/service names are resolved from the facilities
 * and service catalog. An optional `unit` narrows the query server-side.
 */

interface Props {
  /** Facility id to filter the ledger by (optional). */
  unit?: string
}

export default function ConsumptionLedger({ unit }: Props) {
  const [rows, setRows] = useState<ExamConsumptionRow[]>([])
  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [services, setServices] = useState<ConcessionServiceLite[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const qs = unit ? `?unit=${encodeURIComponent(unit)}` : ''
      const [ledger, facs, svcs] = await Promise.all([
        apiFetch<Listish<ExamConsumptionRow>>(`/api/v1/concession/exam-consumptions/${qs}`),
        apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/').catch(() => []),
        apiFetch<Listish<ConcessionServiceLite>>('/api/v1/concession/services/').catch(() => []),
      ])
      setRows(unwrap(ledger))
      setFacilities(unwrap(facs))
      setServices(unwrap(svcs))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [unit])

  useEffect(() => {
    load()
  }, [load])

  const unitName = useMemo(() => {
    const map = new Map(facilities.map((f) => [String(f.id), f.name]))
    return (id: string) => map.get(String(id)) ?? id
  }, [facilities])

  const serviceLabel = useMemo(() => {
    const map = new Map(services.map((s) => [String(s.id), s]))
    return (id: number) => map.get(String(id))
  }, [services])

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">Consumo de exames</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        Ledger imutável de consumo por exame — cada linha registra o custo apropriado no momento da
        realização.
      </p>

      {error && (
        <div className="mt-3">
          <SectionState
            title="Erro ao carregar o consumo."
            detail="Verifique sua conexão e tente novamente."
            tone="critical"
          />
        </div>
      )}

      {loading && <p className="mt-3 text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && rows.length === 0 && (
        <div className="mt-3">
          <SectionState
            title="Nenhum consumo registrado."
            detail="Assim que exames forem realizados, o consumo de material aparece aqui."
          />
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
                <th className="px-3 py-2">Realizado em</th>
                <th className="px-3 py-2">Serviço</th>
                <th className="px-3 py-2">Unidade</th>
                <th className="px-3 py-2">Referência</th>
                <th className="px-3 py-2 text-right">Custo</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => {
                const svc = serviceLabel(r.service)
                return (
                  <tr key={r.id} className="text-slate-700">
                    <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(r.performed_at)}</td>
                    <td className="px-3 py-2">
                      {svc ? (
                        <>
                          <span className="font-medium text-slate-900">{svc.name}</span>
                          <span className="ml-2 text-xs text-slate-400">{svc.code}</span>
                        </>
                      ) : (
                        <span className="text-slate-400">Serviço #{r.service}</span>
                      )}
                    </td>
                    <td className="px-3 py-2">{unitName(r.unit)}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{r.external_ref}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatBRL(r.cost_snapshot)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
