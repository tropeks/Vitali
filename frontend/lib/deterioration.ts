/**
 * Clinical-deterioration surface helpers (wedge D3 — NEWS2 early warning).
 *
 * The deterministic NEWS2 engine (DeteriorationService) persists
 * `DeteriorationAlert` rows when a patient's vital signs cross the risk band.
 * `DeteriorationAlertsView` lists the OPEN ones (sickest first); the clinical
 * team reviews each (score, band, the contributing parameters) and "reconhece"
 * (acknowledges) it, optionally with a note.
 *
 * ADVISE / ESCALATION ONLY — there is NO gate on vitals recording anywhere in
 * this wedge. When the `deterioration_safety` flag is OFF the backend returns an
 * empty list (`deterioration_safety_enabled: false`).
 */
import { apiFetch } from './api'

export type DeteriorationBand = 'low' | 'low_medium' | 'medium' | 'high'

export interface DeteriorationAlert {
  id: string
  encounter_id: string
  patient_id: string
  patient_name: string
  vital_signs_id: string
  score: number
  band: DeteriorationBand
  band_display: string
  /** Per-parameter NEWS2 sub-scores, e.g. { respiratory_rate: 3, heart_rate: 2 }. */
  breakdown: Record<string, number>
  any_param_three: boolean
  spo2_scale: number
  severity: 'advise' | 'escalation'
  severity_display: string
  status: string
  message: string
  engine_version: string
  acknowledged_by: string | null
  acknowledged_at: string | null
  note: string
  created_at: string
  updated_at: string
}

export interface DeteriorationResponse {
  alerts: DeteriorationAlert[]
  deterioration_safety_enabled: boolean
}

/**
 * GET the open NEWS2 deterioration alerts (sickest first). Optionally scope to a
 * single encounter. Returns an empty `alerts` list (with
 * `deterioration_safety_enabled: false`) when the feature flag is off.
 */
export async function fetchDeteriorationAlerts(
  encounterId?: string,
): Promise<DeteriorationResponse> {
  const qs = encounterId ? `?encounter_id=${encodeURIComponent(encounterId)}` : ''
  return apiFetch<DeteriorationResponse>(`/api/v1/deterioration-alerts/${qs}`)
}

/**
 * Acknowledge a deterioration alert. The note is OPTIONAL — a NEWS2 alert is an
 * advisory early-warning, never a hard block, so the backend imposes no minimum.
 * Acknowledging removes the alert from the open list (and frees the encounter's
 * open slot so a later re-deterioration raises a new alert).
 */
export async function acknowledgeDeteriorationAlert(alertId: string, note = ''): Promise<void> {
  await apiFetch(`/api/v1/deterioration-alerts/${alertId}/acknowledge/`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

/** Human-readable label for each NEWS2 parameter key (pt-BR). */
export const PARAM_LABELS: Record<string, string> = {
  respiratory_rate: 'FR',
  spo2: 'SpO2',
  supplemental_oxygen: 'O2 suplementar',
  systolic_bp: 'PAS',
  heart_rate: 'FC',
  temperature: 'Temp',
  consciousness: 'Consciência',
}
