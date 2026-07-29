'use client'

import { useEffect, useMemo, useState } from 'react'
import { apiFetch, ApiError } from '@/lib/api'
import {
  CERTOS_ORDER,
  CERTO_LABELS,
  aboRhLabel,
  labelOf,
  normalizeList,
  URGENCIA_OPTIONS,
  type BloodBagDTO,
  type ListResponse,
  type TransfusionAdministration,
  type TransfusionCheck,
  type TransfusionCheckError,
  type TransfusionCheckPayload,
  type TransfusionRequest,
} from './transfusion-types'

interface BedsideCheckProps {
  request: TransfusionRequest
  /** Barcode/MRN scanned off the patient wristband — prefills the check. */
  patientBarcode: string
  onClose: () => void
  onChecked: (request: TransfusionRequest, administration: TransfusionAdministration) => void
}

/**
 * Checagem transfusional beira-leito (H6) — the blood-transfusion counterpart of
 * the BCMA `BcmaCheckModal`. The requisição does NOT carry a bag, so the nurse
 * PICKS the physical bolsa here from the available stock
 * (`GET /api/v1/blood-bags/`, filtered to available/liberada), scans the patient
 * wristband + bag DIN, and runs
 * `POST /api/v1/transfusion-requests/<pk>/checar/`. On 201 the administração is
 * recorded; on 422 the "5 certos" breakdown
 * (paciente/bolsa/componente/compatibilidade/validade) is surfaced, requiring an
 * override justification (+ optional testemunha) to proceed; a 409 means the
 * bolsa/requisição is not liberada.
 */
export default function BedsideCheck({
  request,
  patientBarcode,
  onClose,
  onChecked,
}: BedsideCheckProps) {
  const [bags, setBags] = useState<BloodBagDTO[]>([])
  const [bag, setBag] = useState('')
  const [patientCode, setPatientCode] = useState(patientBarcode)
  const [bagCode, setBagCode] = useState('')
  const [witness, setWitness] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [failed, setFailed] = useState<TransfusionCheck | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const blocked = failed != null && !failed.ok

  /** Bag ids already crossmatched/reserved for this requisição (the recommended ones). */
  const crossmatchedBagIds = useMemo(
    () => new Set((request.crossmatches ?? []).map((cm) => cm.bag)),
    [request.crossmatches],
  )

  useEffect(() => {
    let alive = true
    apiFetch<ListResponse<BloodBagDTO> | BloodBagDTO[]>('/api/v1/blood-bags/')
      .then((data) => {
        if (!alive) return
        const available = normalizeList(data).filter(
          (b) => b.available || b.serology_status === 'liberada',
        )
        setBags(available)
        // Prefer a bag already crossmatched for this requisição, else the first available.
        const preferred =
          available.find((b) => crossmatchedBagIds.has(b.id)) ?? available[0]
        if (preferred) {
          setBag(preferred.id)
          setBagCode(preferred.identifier)
        }
      })
      .catch(() => {
        /* stock optional — the nurse can still scan the DIN into bag_barcode */
      })
    return () => {
      alive = false
    }
  }, [crossmatchedBagIds])

  async function runCheck() {
    setSubmitting(true)
    setError(null)
    const reason = overrideReason.trim()
    const witnessId = witness.trim()
    const body: TransfusionCheckPayload = {
      bag,
      patient_barcode: patientCode.trim(),
      bag_barcode: bagCode.trim(),
    }
    if (reason) body.override_reason = reason
    if (witnessId) body.witness = witnessId
    try {
      const administration = await apiFetch<TransfusionAdministration>(
        `/api/v1/transfusion-requests/${request.id}/checar/`,
        { method: 'POST', body: JSON.stringify(body) },
      )
      onChecked(request, administration)
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const payload = err.body as TransfusionCheckError
        setFailed(payload?.checagem ?? null)
        return
      }
      if (err instanceof ApiError && err.status === 409) {
        setError('Bolsa/requisição não liberada para transfusão. Verifique no banco de sangue.')
        return
      }
      if (err instanceof ApiError && err.status === 400) {
        setError('Bolsa não encontrada. Selecione uma bolsa válida.')
        return
      }
      setError('Erro ao registrar a checagem. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Checagem transfusional beira-leito"
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-white bg-neu-panel p-5 shadow-lg">
        <div>
          <h2 className="text-lg font-semibold text-neu-ink">Checagem transfusional beira-leito</h2>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            {request.component_display || request.component_code || 'Hemocomponente'} ·{' '}
            {request.quantidade} un · {labelOf(URGENCIA_OPTIONS, request.urgencia)}
          </p>
        </div>

        <div className="space-y-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Bolsa (estoque liberado)</span>
            <select
              aria-label="Bolsa"
              value={bag}
              onChange={(e) => {
                const id = e.target.value
                setBag(id)
                const picked = bags.find((b) => b.id === id)
                if (picked) setBagCode(picked.identifier)
              }}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            >
              <option value="">Selecione a bolsa…</option>
              {bags.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.identifier} · {aboRhLabel(b.abo, b.rh_factor)}
                  {b.component_display ? ` · ${b.component_display}` : ''}
                  {crossmatchedBagIds.has(b.id) ? ' · (prova cruzada)' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Código do paciente (pulseira)</span>
            <input
              aria-label="Código do paciente"
              value={patientCode}
              onChange={(e) => setPatientCode(e.target.value)}
              className="w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
              autoComplete="off"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-neu-ink">Código da bolsa (DIN)</span>
            <input
              aria-label="Código da bolsa"
              value={bagCode}
              onChange={(e) => setBagCode(e.target.value)}
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
            <div className="space-y-1.5" role="list" aria-label="Checagem dos 5 certos da transfusão">
              {CERTOS_ORDER.map((certo) => {
                const passed = failed[certo]
                return (
                  <div
                    key={certo}
                    role="listitem"
                    data-testid={`certo-${certo}`}
                    className={`flex items-center justify-between rounded-md border px-3 py-2 text-sm ${
                      passed
                        ? 'border-slate-200 bg-neu-panel text-neu-ink'
                        : 'border-red-300 bg-red-50 text-red-800'
                    }`}
                  >
                    <span className="font-medium">{CERTO_LABELS[certo]}</span>
                    <span
                      className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${
                        passed
                          ? 'border-green-200 bg-green-100 text-green-700'
                          : 'border-red-200 bg-red-100 text-red-700'
                      }`}
                    >
                      {passed ? 'Certo' : 'Falhou'}
                    </span>
                  </div>
                )
              })}
            </div>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-red-800">
                Segundo checador (testemunha) — opcional
              </span>
              <input
                aria-label="Segundo checador"
                value={witness}
                onChange={(e) => setWitness(e.target.value)}
                className="w-full rounded-md border border-red-300 bg-white px-3 py-2 text-neu-ink"
                placeholder="Id do profissional que testemunhou a dupla checagem."
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-red-800">Justificativa do override</span>
              <textarea
                aria-label="Justificativa do override"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                rows={2}
                className="w-full rounded-md border border-red-300 bg-white px-3 py-2 text-neu-ink"
                placeholder="Justifique a transfusão apesar da falha na checagem."
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
              disabled={submitting || overrideReason.trim() === '' || bag === ''}
              className="rounded-md bg-red-600 px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              Transfundir com justificativa
            </button>
          ) : (
            <button
              type="button"
              onClick={runCheck}
              disabled={
                submitting || bag === '' || bagCode.trim() === '' || patientCode.trim() === ''
              }
              className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              Verificar e transfundir
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
