'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { MAINTENANCE_ENDPOINTS, type AssetOption, type MaintenanceTicket } from './maintenanceMeta'
import type { FacilityOption } from './assetMeta'

/**
 * MaintenanceTicketFormModal — create a MaintenanceTicket (Concessão →
 * Manutenção). Only the fields exposed on the board's "+ Novo ticket" form
 * are collected here (asset, facility, description); status defaults to
 * OPEN server-side and the remaining fields (cost, evidence_url, resolution)
 * are set later via the start/complete transitions.
 * POST /api/v1/concession/maintenance-tickets/
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

export interface MaintenanceTicketFormModalProps {
  open: boolean
  assets: AssetOption[]
  facilities: FacilityOption[]
  onClose: () => void
  onSuccess?: (ticket: MaintenanceTicket) => void
}

export default function MaintenanceTicketFormModal({
  open,
  assets,
  facilities,
  onClose,
  onSuccess,
}: MaintenanceTicketFormModalProps) {
  const [asset, setAsset] = useState('')
  const [facility, setFacility] = useState('')
  const [description, setDescription] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')

  useEffect(() => {
    if (!open) return
    setAsset('')
    setFacility('')
    setDescription('')
    setFieldErrors({})
    setGlobalError('')
  }, [open])

  if (!open) return null

  const valid = asset.trim().length > 0 && description.trim().length > 0

  async function handleSubmit() {
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const payload = {
      asset,
      facility: facility === '' ? null : facility,
      description: description.trim(),
    }

    try {
      const created = await apiFetch<MaintenanceTicket>(MAINTENANCE_ENDPOINTS.tickets, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess?.(created)
      onClose()
    } catch (err) {
      if (err instanceof ApiError) {
        const errors = extractFieldErrors(err.body)
        if (Object.keys(errors).length > 0) setFieldErrors(errors)
        else setGlobalError('Não foi possível criar o ticket.')
      } else {
        setGlobalError('Não foi possível criar o ticket.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">Novo ticket</h2>
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

          <div>
            <label htmlFor="ticket-asset" className={LABEL_CLASS}>
              Ativo
            </label>
            <select
              id="ticket-asset"
              className={SELECT_CLASS}
              value={asset}
              onChange={(e) => setAsset(e.target.value)}
            >
              <option value="">Selecionar ativo</option>
              {assets.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.asset_tag} — {a.name}
                </option>
              ))}
            </select>
            {fieldErrors.asset && <p className="mt-1 text-xs text-red-600">{fieldErrors.asset}</p>}
          </div>

          <div>
            <label htmlFor="ticket-facility" className={LABEL_CLASS}>
              Unidade
            </label>
            <select
              id="ticket-facility"
              className={SELECT_CLASS}
              value={facility}
              onChange={(e) => setFacility(e.target.value)}
            >
              <option value="">Sem unidade associada</option>
              {facilities.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="ticket-description" className={LABEL_CLASS}>
              Descrição
            </label>
            <textarea
              id="ticket-description"
              rows={3}
              className={INPUT_CLASS}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Descreva o problema encontrado"
            />
            {fieldErrors.description && (
              <p className="mt-1 text-xs text-red-600">{fieldErrors.description}</p>
            )}
          </div>
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
            {submitting ? 'Criando...' : 'Criar ticket'}
          </button>
        </div>
      </div>
    </div>
  )
}
