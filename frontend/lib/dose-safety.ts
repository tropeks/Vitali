/**
 * Dose-safety interception helpers (PR C/3 — deterministic dose engine).
 *
 * Signing/dispensing return HTTP 409 with a `dose_safety_block` body when the
 * deterministic dose engine raises a blocking alert. The clinician must
 * acknowledge each blocking alert (with a justification) and retry.
 *
 * The reachable interception point wired in the UI is the pharmacy DISPENSE
 * gate (see app/(dashboard)/farmacia/dispense/page.tsx).
 */
import { ApiError, apiFetch } from './api'

export interface DoseAlert {
  id: string
  prescription_item: string
  alert_type: string
  severity: string
  status: string
  message: string
  recommendation: string
  blocking_kind?: string
}

export interface DoseSafetyBlock {
  code: 'dose_safety_block'
  detail: string
  alerts: DoseAlert[]
}

/**
 * Returns the parsed block body when `err` is an ApiError carrying a 409
 * `dose_safety_block` response (with an alerts array), otherwise null.
 */
export function isDoseSafetyBlock(err: unknown): DoseSafetyBlock | null {
  if (!(err instanceof ApiError)) return null
  if (err.status !== 409) return null
  const body = err.body
  if (
    body &&
    typeof body === 'object' &&
    body.code === 'dose_safety_block' &&
    Array.isArray(body.alerts)
  ) {
    return body as DoseSafetyBlock
  }
  return null
}

/**
 * A weight-gate block is NON-overridable: the clinician cannot reason it away,
 * they must record the patient's weight. We key on the structural
 * `blocking_kind` field (backend single source of truth:
 * apps/emr/services/dose_safety.py::classify_blocking_kind), falling back to the
 * stable recommendation copy only defensively for older payloads that predate
 * the field.
 */
export function isWeightGate(alert: DoseAlert): boolean {
  return (
    alert.blocking_kind === 'weight_gate' ||
    alert.recommendation.startsWith('Registre/atualize o peso')
  )
}

/**
 * Human label (pt-BR) for a blocking alert, by its structural `blocking_kind`.
 * The 409 payload now mixes dose, allergy-conflict and drug-interaction blocks
 * (allergy wedge A1/A3) through the same modal, so the row header names WHICH
 * kind of safety check fired. Falls back to a generic label for older payloads.
 */
export function blockingKindLabel(alert: DoseAlert): string {
  switch (alert.blocking_kind) {
    case 'weight_gate':
      return 'Peso necessário'
    case 'allergy_conflict':
      return 'Conflito de alergia'
    case 'drug_interaction':
      return 'Interação medicamentosa'
    case 'out_of_range':
      return 'Dose fora do intervalo'
    case 'unit_mismatch':
      return 'Unidade incompatível'
    default:
      if (alert.alert_type === 'allergy') return 'Alergia'
      if (alert.alert_type === 'drug_interaction') return 'Interação medicamentosa'
      return 'Verificação de dose'
  }
}

/**
 * Acknowledge a blocking dose alert with a clinical justification, then the
 * caller retries the original action. POSTs to the shared acknowledge endpoint.
 */
export async function acknowledgeDoseAlert(alertId: string, reason: string): Promise<void> {
  await apiFetch(`/api/v1/safety-alerts/${alertId}/acknowledge/`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}
