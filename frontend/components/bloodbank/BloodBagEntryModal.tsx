'use client'

import { useState } from 'react'
import { PackagePlus, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  ABO_OPTIONS,
  apiErrorDetail,
  RH_OPTIONS,
  todayISO,
  type Abo,
  type BloodComponentDTO,
  type RhFactor,
} from './bloodbank-types'

interface BloodBagEntryModalProps {
  onClose: () => void
  onCreated: () => void
}

/**
 * Entrada de bolsa (hemoterapia.manage) — cadastra uma nova bolsa via POST
 * /api/v1/blood-bags/. The bag defaults to serology_status=quarentena
 * server-side (only the RDC 34 triagem releases it). The hemocomponente is
 * picked from the governed catalog (`/blood-components/?q=`).
 */
export default function BloodBagEntryModal({ onClose, onCreated }: BloodBagEntryModalProps) {
  const [identifier, setIdentifier] = useState('')
  const [component, setComponent] = useState<BloodComponentDTO | null>(null)
  const [abo, setAbo] = useState<Abo>('O')
  const [rhFactor, setRhFactor] = useState<RhFactor>('positivo')
  const [volumeMl, setVolumeMl] = useState('450')
  const [collectionDate, setCollectionDate] = useState(todayISO())
  const [expiryDate, setExpiryDate] = useState('')
  const [irradiada, setIrradiada] = useState(false)
  const [leucodepletada, setLeucodepletada] = useState(false)
  const [aferese, setAferese] = useState(false)
  const [lot, setLot] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!identifier.trim()) {
      setError('Informe o identificador/DIN da bolsa.')
      return
    }
    if (!component) {
      setError('Selecione o hemocomponente.')
      return
    }
    if (!expiryDate) {
      setError('Informe a data de validade.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch('/api/v1/blood-bags/', {
        method: 'POST',
        body: JSON.stringify({
          identifier: identifier.trim(),
          component: component.id,
          abo,
          rh_factor: rhFactor,
          volume_ml: Number(volumeMl) || 0,
          collection_date: collectionDate,
          expiry_date: expiryDate,
          irradiada,
          leucodepletada,
          aferese,
          lot: lot.trim(),
        }),
      })
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
        setError(
          apiErrorDetail(err.body, 'Não foi possível cadastrar a bolsa — verifique o DIN (único).')
        )
        return
      }
      setError('Não foi possível cadastrar a bolsa. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Cadastrar bolsa de sangue"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-neu-modal">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <PackagePlus size={18} className="text-neu-brand" aria-hidden />
            <h2 className="text-base font-semibold text-neu-ink">Entrada de bolsa</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <label className="block text-xs font-semibold text-neu-inkSoft">
            Identificador / DIN
            <input
              aria-label="Identificador/DIN"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder="Ex.: DIN-2026-000123"
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
            />
          </label>

          <div className="text-xs font-semibold text-neu-inkSoft">
            Hemocomponente
            <div className="mt-1">
              <RemoteCombobox<BloodComponentDTO>
                label="Hemocomponente"
                endpoint="/api/v1/blood-components/"
                queryParam="q"
                value={component}
                getKey={(item) => String(item.id)}
                getLabel={(item) => `${item.code} — ${item.display}`}
                onChange={setComponent}
                placeholder="Buscar hemocomponente..."
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Grupo ABO
              <select
                aria-label="Grupo ABO"
                value={abo}
                onChange={(e) => setAbo(e.target.value as Abo)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              >
                {ABO_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Fator Rh
              <select
                aria-label="Fator Rh"
                value={rhFactor}
                onChange={(e) => setRhFactor(e.target.value as RhFactor)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              >
                {RH_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Volume (mL)
              <input
                type="number"
                aria-label="Volume (mL)"
                value={volumeMl}
                onChange={(e) => setVolumeMl(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              />
            </label>
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Coleta
              <input
                type="date"
                aria-label="Data de coleta"
                value={collectionDate}
                onChange={(e) => setCollectionDate(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              />
            </label>
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Validade
              <input
                type="date"
                aria-label="Data de validade"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              />
            </label>
          </div>

          <fieldset className="flex flex-wrap gap-4 text-xs text-neu-ink">
            <legend className="sr-only">Atributos da bolsa</legend>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={irradiada} onChange={(e) => setIrradiada(e.target.checked)} />
              Irradiada
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={leucodepletada}
                onChange={(e) => setLeucodepletada(e.target.checked)}
              />
              Leucodepletada
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={aferese} onChange={(e) => setAferese(e.target.checked)} />
              Aférese
            </label>
          </fieldset>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Lote (opcional)
            <input
              aria-label="Lote"
              value={lot}
              onChange={(e) => setLot(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
            />
          </label>

          <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            A bolsa entra em quarentena até a triagem sorológica (RDC 34) liberá-la.
          </p>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-neu-inkSoft hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? 'Cadastrando...' : 'Cadastrar bolsa'}
          </button>
        </div>
      </div>
    </div>
  )
}
