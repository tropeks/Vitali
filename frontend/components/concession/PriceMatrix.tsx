'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  formatBRL,
  unwrap,
  type ConcessionService,
  type ContractPrice,
  type FacilityOption,
  type Listish,
} from './contractMeta'

/**
 * PriceMatrix — per-contract service pricing editor.
 *
 * Rows = ConcessionService. Each service has one contract-scoped price
 * (`unit: null`) plus optional per-unit override rows (`unit` set). A
 * unit-scoped price overrides the contract-scoped price for that service on
 * that unit. Writes hit /api/v1/contract-prices/ (POST new, PUT existing).
 */

const INPUT_CLASS =
  'w-32 border border-slate-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
const SELECT_CLASS =
  'border border-slate-200 rounded-lg px-2 py-1 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500'
const SAVE_BTN =
  'rounded-lg bg-neu-brand px-3 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50'

interface PriceMatrixProps {
  contractId: string
  services: ConcessionService[]
  facilities: FacilityOption[]
}

interface OverrideDraft {
  unit: string
  price: string
  isBillable: boolean
}

export default function PriceMatrix({ contractId, services, facilities }: PriceMatrixProps) {
  const [prices, setPrices] = useState<ContractPrice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [savingKey, setSavingKey] = useState<string | null>(null)

  // Local edit buffers for the contract-scoped price of each service.
  const [priceInputs, setPriceInputs] = useState<Record<string, string>>({})
  const [billableInputs, setBillableInputs] = useState<Record<string, boolean>>({})

  // Per-service override draft rows (only rendered when opened).
  const [drafts, setDrafts] = useState<Record<string, OverrideDraft>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<Listish<ContractPrice>>(
        `/api/v1/contract-prices/?contract=${contractId}`
      )
      setPrices(unwrap(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [contractId])

  useEffect(() => {
    load()
  }, [load])

  // Seed the contract-scoped edit buffers from loaded prices.
  const contractScoped = useMemo(() => {
    const map: Record<string, ContractPrice> = {}
    for (const p of prices) {
      if (p.unit == null) map[p.service] = p
    }
    return map
  }, [prices])

  useEffect(() => {
    const nextPrice: Record<string, string> = {}
    const nextBillable: Record<string, boolean> = {}
    for (const s of services) {
      const existing = contractScoped[s.id]
      nextPrice[s.id] = existing?.price ?? ''
      nextBillable[s.id] = existing?.is_billable ?? true
    }
    setPriceInputs(nextPrice)
    setBillableInputs(nextBillable)
  }, [services, contractScoped])

  const overridesByService = useMemo(() => {
    const map: Record<string, ContractPrice[]> = {}
    for (const p of prices) {
      if (p.unit != null) (map[p.service] ??= []).push(p)
    }
    return map
  }, [prices])

  async function saveContractPrice(service: ConcessionService) {
    const existing = contractScoped[service.id]
    const payload = {
      contract: contractId,
      unit: null,
      service: service.id,
      price: (priceInputs[service.id] ?? '').trim(),
      is_billable: billableInputs[service.id] ?? true,
    }
    setSavingKey(service.id)
    try {
      await apiFetch(
        existing ? `/api/v1/contract-prices/${existing.id}/` : '/api/v1/contract-prices/',
        {
          method: existing ? 'PUT' : 'POST',
          body: JSON.stringify(payload),
        }
      )
      await load()
    } catch {
      setError(true)
    } finally {
      setSavingKey(null)
    }
  }

  function openDraft(serviceId: string) {
    setDrafts((prev) => ({
      ...prev,
      [serviceId]: { unit: '', price: '', isBillable: true },
    }))
  }

  function updateDraft(serviceId: string, patch: Partial<OverrideDraft>) {
    setDrafts((prev) => ({ ...prev, [serviceId]: { ...prev[serviceId], ...patch } }))
  }

  async function saveOverride(service: ConcessionService) {
    const draft = drafts[service.id]
    if (!draft || !draft.unit) return
    const payload = {
      contract: contractId,
      unit: draft.unit,
      service: service.id,
      price: draft.price.trim(),
      is_billable: draft.isBillable,
    }
    setSavingKey(`ov-${service.id}`)
    try {
      await apiFetch('/api/v1/contract-prices/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setDrafts((prev) => {
        const next = { ...prev }
        delete next[service.id]
        return next
      })
      await load()
    } catch {
      setError(true)
    } finally {
      setSavingKey(null)
    }
  }

  const facilityName = useCallback(
    (id: string | null) => facilities.find((f) => f.id === id)?.name ?? id ?? '—',
    [facilities]
  )

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">Matriz de preços</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        Preço por serviço no contrato. Overrides por unidade prevalecem sobre o preço do contrato.
      </p>

      {error && (
        <div className="mt-3">
          <SectionState
            title="Erro ao carregar preços."
            detail="Tente novamente."
            tone="critical"
          />
        </div>
      )}
      {loading && <p className="mt-3 text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && services.length === 0 && (
        <p className="mt-3 text-sm text-neu-inkMuted">
          Cadastre serviços no catálogo para precificar este contrato.
        </p>
      )}

      {!loading && services.length > 0 && (
        <div className="mt-3 space-y-3">
          {services.map((s) => {
            const overrides = overridesByService[s.id] ?? []
            const draft = drafts[s.id]
            return (
              <div key={s.id} className="rounded-lg border border-slate-100 p-3">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="min-w-40 flex-1">
                    <p className="text-sm font-medium text-slate-900">{s.name}</p>
                    <p className="text-xs text-slate-400">{s.code}</p>
                  </div>
                  <input
                    aria-label={`Preço ${s.code}`}
                    type="text"
                    inputMode="decimal"
                    placeholder="0,00"
                    className={INPUT_CLASS}
                    value={priceInputs[s.id] ?? ''}
                    onChange={(e) =>
                      setPriceInputs((prev) => ({ ...prev, [s.id]: e.target.value }))
                    }
                  />
                  <label className="flex items-center gap-1.5 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      aria-label={`Faturável ${s.code}`}
                      checked={billableInputs[s.id] ?? true}
                      onChange={(e) =>
                        setBillableInputs((prev) => ({ ...prev, [s.id]: e.target.checked }))
                      }
                    />
                    Faturável
                  </label>
                  <button
                    type="button"
                    className={SAVE_BTN}
                    disabled={savingKey === s.id}
                    onClick={() => saveContractPrice(s)}
                  >
                    {savingKey === s.id ? '...' : `Salvar ${s.code}`}
                  </button>
                  <button
                    type="button"
                    className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                    onClick={() => openDraft(s.id)}
                  >
                    {`Adicionar override ${s.code}`}
                  </button>
                </div>

                {overrides.length > 0 && (
                  <ul className="mt-2 space-y-1 pl-1">
                    {overrides.map((o) => (
                      <li key={o.id} className="text-xs text-slate-500">
                        {facilityName(o.unit)}: {formatBRL(o.price)}
                        {o.is_billable ? '' : ' (não faturável)'}
                      </li>
                    ))}
                  </ul>
                )}

                {draft && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-2">
                    <select
                      aria-label={`Unidade do override ${s.code}`}
                      className={SELECT_CLASS}
                      value={draft.unit}
                      onChange={(e) => updateDraft(s.id, { unit: e.target.value })}
                    >
                      <option value="">Selecione a unidade</option>
                      {facilities.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label={`Preço override ${s.code}`}
                      type="text"
                      inputMode="decimal"
                      placeholder="0,00"
                      className={INPUT_CLASS}
                      value={draft.price}
                      onChange={(e) => updateDraft(s.id, { price: e.target.value })}
                    />
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        aria-label={`Faturável override ${s.code}`}
                        checked={draft.isBillable}
                        onChange={(e) => updateDraft(s.id, { isBillable: e.target.checked })}
                      />
                      Faturável
                    </label>
                    <button
                      type="button"
                      className={SAVE_BTN}
                      disabled={!draft.unit || savingKey === `ov-${s.id}`}
                      onClick={() => saveOverride(s)}
                    >
                      {`Salvar override ${s.code}`}
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
