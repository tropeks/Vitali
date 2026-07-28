'use client'

import { useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import BcmaFiveRights from './BcmaFiveRights'
import {
  formatDose,
} from './MarList'
import type {
  BcmaCheckError,
  FiveRights,
  MarDueItem,
  MedicationAdministrationRecord,
} from './mar-types'

interface BcmaCheckModalProps {
  item: MarDueItem
  /** Barcode/MRN scanned off the patient at bedside — prefills the check. */
  patientBarcode: string
  onClose: () => void
  onRecorded: (item: MarDueItem, record: MedicationAdministrationRecord) => void
}

/**
 * BCMA beira-leito: scan the medication, run `POST /api/v1/emar/check/`, and
 * either record the administration (201) or surface the "5 certos" breakdown
 * (422) and require an override justification to proceed.
 */
export default function BcmaCheckModal({
  item,
  patientBarcode,
  onClose,
  onRecorded,
}: BcmaCheckModalProps) {
  const [patientCode, setPatientCode] = useState(patientBarcode)
  const [medicationCode, setMedicationCode] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [failed, setFailed] = useState<FiveRights | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function runCheck() {
    setSubmitting(true)
    setError(null)
    const reason = overrideReason.trim()
    const body: Record<string, string> = {
      prescription_item: item.id,
      patient_barcode: patientCode.trim(),
      medication_barcode: medicationCode.trim(),
    }
    if (reason) body.override_reason = reason
    try {
      const record = await apiFetch<MedicationAdministrationRecord>('/api/v1/emar/check/', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onRecorded(item, record)
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const payload = err.body as BcmaCheckError
        setFailed(payload?.bcma ?? null)
        return
      }
      setError('Erro ao registrar a checagem. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  const blocked = failed != null && !failed.ok

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Checagem beira-leito"
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Checagem beira-leito</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            {item.drug_name} · {formatDose(item.dose_amount, item.dose_unit)}
            {item.route ? ` · ${item.route}` : ''}
          </p>
        </div>

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Código do paciente</span>
            <input
              aria-label="Código do paciente"
              value={patientCode}
              onChange={(e) => setPatientCode(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              autoComplete="off"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Código do medicamento</span>
            <input
              aria-label="Código do medicamento"
              value={medicationCode}
              onChange={(e) => setMedicationCode(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              autoComplete="off"
              autoFocus
            />
          </label>
        </div>

        {blocked && failed && (
          <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-sm font-semibold text-red-800">
              Falha na checagem dos 5 certos — confira os itens destacados.
            </p>
            <BcmaFiveRights result={failed} />
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-red-800">
                Justificativa do override
              </span>
              <textarea
                aria-label="Justificativa do override"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                rows={2}
                className="w-full rounded-md border border-red-300 bg-white px-3 py-2 text-neu-ink"
                placeholder="Justifique a administração apesar da falha na checagem."
              />
            </label>
          </div>
        )}

        {error && <p className="text-sm text-red-700">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-panel"
          >
            Cancelar
          </button>
          {blocked ? (
            <button
              type="button"
              onClick={runCheck}
              disabled={submitting || overrideReason.trim() === ''}
              className="rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              Administrar com justificativa
            </button>
          ) : (
            <button
              type="button"
              onClick={runCheck}
              disabled={submitting || medicationCode.trim() === ''}
              className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              Verificar e administrar
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
