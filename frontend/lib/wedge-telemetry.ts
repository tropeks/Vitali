/**
 * Wedge operational telemetry (S30-04).
 *
 * Reads per-wedge operational metrics for the three deterministic safety wedges
 * (no-show, stockout, deterioration) from `GET /api/v1/wedge-telemetry/`. The
 * backend reads persisted verdict rows + the AuditLog flywheel trail; it never
 * re-runs an engine.
 *
 * OBSERVABILITY ONLY. Wedges are pure deterministic algorithms, so `engine` is
 * always `"deterministic"` (no model/latency/confidence). Metrics that cannot be
 * computed are returned as `null` — `override_rate` is null when there are no
 * alerts in the window, and `outcome_counts` is null for wedges whose verdict
 * model has no outcome field (deterioration).
 */
import { apiFetch } from './api'

export interface WedgeFlywheel {
  /** outcome label → count, or null when the wedge has no outcome field. */
  outcome_counts: Record<string, number> | null
  /** Number of "<wedge>_graded" AuditLog events in the window. */
  graded_count: number
}

export interface WedgeTelemetry {
  key: string
  enabled: boolean
  alert_count: number
  acknowledged_count: number
  /** acknowledged / total, or null when there are no alerts (no division). */
  override_rate: number | null
  flywheel: WedgeFlywheel
  /** Always "deterministic" — wedges are pure algorithms. */
  engine: string
}

export interface WedgeTelemetryPayload {
  days: number
  wedges: WedgeTelemetry[]
}

/** GET the per-wedge operational telemetry for the last `days` (default 30). */
export async function fetchWedgeTelemetry(days = 30): Promise<WedgeTelemetryPayload> {
  return apiFetch<WedgeTelemetryPayload>(`/api/v1/wedge-telemetry/?days=${encodeURIComponent(days)}`)
}
