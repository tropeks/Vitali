/**
 * No-show risk surface helpers (wedge N3 — front-desk no-show prediction).
 *
 * The deterministic NoShowService scores each upcoming appointment from the
 * patient's own history and persists a `NoShowRisk`. `NoShowRiskView` lists the
 * OPEN ones (highest score first); reception reviews each (score, band, why) and
 * "reconhece" it after acting (confirming the patient / overbooking).
 *
 * ADVISE / OPERATIONAL ONLY — never blocks booking or check-in. When the
 * `no_show_prediction` flag is OFF the backend returns an empty list
 * (`no_show_prediction_enabled: false`).
 */
import { apiFetch } from './api'

export type NoShowBand = 'low' | 'medium' | 'high'

export interface NoShowRisk {
  id: string
  appointment_id: string
  patient_id: string
  patient_name: string
  appointment_start: string
  appointment_type: string
  appointment_type_display: string
  professional_name: string
  score: string
  band: NoShowBand
  band_display: string
  /** Per-component explanation: base_rate + each fired odds modifier. */
  breakdown: Array<Record<string, unknown>>
  suggested_action: string
  suggested_action_display: string
  status: string
  engine_version: string
  acknowledged_by: string | null
  acknowledged_at: string | null
  note: string
  computed_at: string
}

export interface NoShowResponse {
  risks: NoShowRisk[]
  no_show_prediction_enabled: boolean
  truncated?: boolean
}

/** GET the open no-show risks (sickest first). Optionally filter by band. */
export async function fetchNoShowRisks(band?: NoShowBand): Promise<NoShowResponse> {
  const qs = band ? `?band=${encodeURIComponent(band)}` : ''
  return apiFetch<NoShowResponse>(`/api/v1/no-show-risk/${qs}`)
}

/**
 * Acknowledge a no-show risk (reception handled it). Note optional — advise-only.
 * Acknowledging removes it from the open list.
 */
export async function acknowledgeNoShowRisk(riskId: string, note = ''): Promise<void> {
  await apiFetch(`/api/v1/no-show-risk/${riskId}/acknowledge/`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}
