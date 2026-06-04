/**
 * Controlled-substance diversion surface helpers (wedge C3 — Portaria 344 compliance).
 *
 * The deterministic ControlledSafetyService records a `ControlledAlert` per
 * diversion signal (refill-too-soon / doctor-shopping / quantity-escalation) when
 * a controlled drug is dispensed. `ControlledAlertsView` lists the OPEN ones for
 * pharmacist/compliance review; "reconhecer" acknowledges after review.
 *
 * ADVISE / COMPLIANCE ONLY — nothing here ever blocked a dispensation (the
 * dispense_controlled perm + notes gate governs the act). When the
 * `controlled_safety` flag is OFF the backend returns an empty list.
 */
import { apiFetch } from './api'

export type ControlledSignalKind =
  | 'refill_too_soon'
  | 'multiple_prescribers'
  | 'quantity_escalation'

export interface ControlledAlert {
  id: string
  dispensation_id: string
  patient_id: string
  patient_name: string
  drug: string
  drug_id: string
  controlled_class: string
  signal_kind: ControlledSignalKind
  signal_kind_display: string
  severity: string
  detail: Record<string, unknown>
  status: string
  engine_version: string
  acknowledged_by: string | null
  acknowledged_at: string | null
  note: string
  created_at: string
}

export interface ControlledResponse {
  alerts: ControlledAlert[]
  controlled_safety_enabled: boolean
  truncated?: boolean
}

/** GET the open controlled-diversion alerts. Optionally filter by signal kind. */
export async function fetchControlledAlerts(
  signalKind?: ControlledSignalKind,
): Promise<ControlledResponse> {
  const qs = signalKind ? `?signal_kind=${encodeURIComponent(signalKind)}` : ''
  return apiFetch<ControlledResponse>(`/api/v1/pharmacy/controlled/alerts/${qs}`)
}

/** Acknowledge a controlled-diversion alert (compliance reviewed it). */
export async function acknowledgeControlledAlert(alertId: string, note = ''): Promise<void> {
  await apiFetch(`/api/v1/pharmacy/controlled/alerts/${alertId}/acknowledge/`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}
