/**
 * Stockout-prediction surface helpers (wedge S3 — proactive supply risk).
 *
 * The deterministic StockoutService persists `StockAlert` rows (stockout_risk +
 * expiry_waste) for the supply manager. `StockRiskView` lists the OPEN ones; the
 * gestor reviews each prediction (predicted date, days-to-stockout / waste qty,
 * a reorder suggestion) and "reconhece" (acknowledges) it.
 *
 * ADVISE ONLY — this is purely proactive. There is NO dispense-time alert and no
 * gate anywhere in this wedge. When the `stockout_safety` flag is OFF the backend
 * returns an empty list (`stockout_safety_enabled: false`).
 */
import { apiFetch } from './api'

export type StockAlertKind = 'stockout_risk' | 'expiry_waste'

export interface StockRiskAlert {
  id: string
  kind: StockAlertKind
  kind_display: string
  drug: string | null
  material: string | null
  product_name: string
  stock_item: string | null
  predicted_date: string | null
  days_to_stockout: string | null
  predicted_waste_qty: string | null
  /** Sized from derived velocity + configured lead time + real balance. */
  suggested_reorder_qty: string | null
  message: string
  severity: string
  status: string
  created_at: string
}

export interface StockRiskResponse {
  alerts: StockRiskAlert[]
  stockout_safety_enabled: boolean
}

/**
 * GET the open predictive supply-risk alerts. Optionally filter by `kind`.
 * Returns an empty `alerts` list (with `stockout_safety_enabled: false`) when the
 * feature flag is off.
 */
export async function fetchStockRisk(kind?: StockAlertKind): Promise<StockRiskResponse> {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : ''
  return apiFetch<StockRiskResponse>(`/api/v1/pharmacy/stock/risk/${qs}`)
}

/**
 * Acknowledge a stock-risk alert. The note is OPTIONAL — these are advise-only
 * alerts, so the backend imposes no minimum length. Acknowledging removes the
 * alert from the open risk list.
 */
export async function acknowledgeStockAlert(alertId: string, note = ''): Promise<void> {
  await apiFetch(`/api/v1/pharmacy/stock-alerts/${alertId}/acknowledge/`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}
