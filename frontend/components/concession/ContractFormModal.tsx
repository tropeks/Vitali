'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  CONTRACT_STATUS_OPTIONS,
  unwrap,
  type ConcessionContract,
  type ContractStatus,
  type FacilityOption,
  type Listish,
} from './contractMeta'

/**
 * ContractFormModal — create / edit a ConcessionContract (comodato).
 * Mirrors ConcessionContractSerializer writable fields. `client` (LegalEntity)
 * is kept nullable and not editable here (only free-text `client_name` is
 * captured in this sprint). Create → POST, edit → PUT the detail endpoint.
 */

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

function extractFieldErrors(body: any): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [key, val] of Object.entries(body)) {
    if (Array.isArray(val) && val.length > 0) errors[key] = String(val[0])
    else if (typeof val === 'string') errors[key] = val
  }
  return errors
}

export interface ContractFormModalProps {
  open: boolean
  contract?: ConcessionContract | null
  onClose: () => void
  onSuccess?: (contract: ConcessionContract) => void
}

export default function ContractFormModal({
  open,
  contract = null,
  onClose,
  onSuccess,
}: ContractFormModalProps) {
  const isEdit = contract != null

  const [name, setName] = useState('')
  const [clientName, setClientName] = useState('')
  const [units, setUnits] = useState<string[]>([])
  const [monthlyValue, setMonthlyValue] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [status, setStatus] = useState<ContractStatus>('ACTIVE')

  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')

  useEffect(() => {
    if (!open) return
    setName(contract?.name ?? '')
    setClientName(contract?.client_name ?? '')
    setUnits(contract?.units ?? [])
    setMonthlyValue(contract?.monthly_value ?? '')
    setStartDate(contract?.start_date ?? '')
    setEndDate(contract?.end_date ?? '')
    setStatus(contract?.status ?? 'ACTIVE')
    setFieldErrors({})
    setGlobalError('')
  }, [open, contract])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/')
      .then((data) => {
        if (!cancelled) setFacilities(unwrap(data))
      })
      .catch(() => {
        if (!cancelled) setFacilities([])
      })
    return () => {
      cancelled = true
    }
  }, [open])

  if (!open) return null

  const valid = name.trim().length > 0

  function toggleUnit(id: string) {
    setUnits((prev) => (prev.includes(id) ? prev.filter((u) => u !== id) : [...prev, id]))
  }

  async function handleSubmit() {
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const payload = {
      name: name.trim(),
      client_name: clientName.trim(),
      client: contract?.client ?? null,
      units,
      monthly_value: monthlyValue.trim() === '' ? null : monthlyValue.trim(),
      start_date: startDate === '' ? null : startDate,
      end_date: endDate === '' ? null : endDate,
      status,
    }

    const path = isEdit
      ? `/api/v1/concession-contracts/${contract!.id}/`
      : '/api/v1/concession-contracts/'

    try {
      const saved = await apiFetch<ConcessionContract>(path, {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess?.(saved)
      onClose()
    } catch (err) {
      if (err instanceof ApiError) {
        const errors = extractFieldErrors(err.body)
        if (Object.keys(errors).length > 0) setFieldErrors(errors)
        else setGlobalError('Não foi possível salvar o contrato.')
      } else {
        setGlobalError('Não foi possível salvar o contrato.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {isEdit ? 'Editar contrato' : 'Novo contrato'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-600"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {globalError && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {globalError}
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label htmlFor="contract-name" className={LABEL_CLASS}>
                Nome do contrato
              </label>
              <input
                id="contract-name"
                className={INPUT_CLASS}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              {fieldErrors.name && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.name}</p>
              )}
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="contract-client" className={LABEL_CLASS}>
                Cliente
              </label>
              <input
                id="contract-client"
                className={INPUT_CLASS}
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="contract-value" className={LABEL_CLASS}>
                Valor mensal (R$)
              </label>
              <input
                id="contract-value"
                type="text"
                inputMode="decimal"
                className={INPUT_CLASS}
                value={monthlyValue}
                onChange={(e) => setMonthlyValue(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="contract-status" className={LABEL_CLASS}>
                Status
              </label>
              <select
                id="contract-status"
                className={SELECT_CLASS}
                value={status}
                onChange={(e) => setStatus(e.target.value as ContractStatus)}
              >
                {CONTRACT_STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="contract-start" className={LABEL_CLASS}>
                Início da vigência
              </label>
              <input
                id="contract-start"
                type="date"
                className={INPUT_CLASS}
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="contract-end" className={LABEL_CLASS}>
                Fim da vigência
              </label>
              <input
                id="contract-end"
                type="date"
                className={INPUT_CLASS}
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>

          <fieldset>
            <legend className={LABEL_CLASS}>Unidades atendidas</legend>
            {facilities.length === 0 ? (
              <p className="text-xs text-slate-500">Nenhuma unidade disponível.</p>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {facilities.map((f) => (
                  <label key={f.id} className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      aria-label={f.name}
                      checked={units.includes(f.id)}
                      onChange={() => toggleUnit(f.id)}
                    />
                    {f.name}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!valid || submitting}
            className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Salvando...' : isEdit ? 'Salvar' : 'Criar contrato'}
          </button>
        </div>
      </div>
    </div>
  )
}
