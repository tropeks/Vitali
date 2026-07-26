// Shared types + helpers for the concession P&L / consumption surface (Sprint
// B6). Mirrors backend/apps/concession serializers_pnl.py + services_pnl.py.
//
// Two typing camps, on purpose:
//   - The P&L roll-up (`/pnl/`) bypasses DRF serializers and is returned as a
//     raw dict, so DRF's JSONEncoder renders Decimals as JSON *numbers* and
//     UUIDs as strings. Money fields there are `number`.
//   - The ledger + material-cost endpoints go through ModelSerializers, so
//     their money fields (`cost_snapshot`, `unit_cost`) are decimal-*strings*.
// `formatBRL` accepts both, so the split is invisible at render time.
//
// The three list endpoints are page-number paginated ({ results: [...] }) and
// expose bare FKs only (no *_name display fields) — callers resolve names from
// the facilities / services / materials lists.

export {
  unwrap,
  formatBRL,
  formatDate,
  type FacilityOption,
  type Listish,
} from './assetMeta'

// ─── P&L roll-up (raw dict — numbers, not decimal-strings) ──────────────────

export interface PnlByServiceLine {
  service: number
  service_code: string
  service_name: string
  exam_volume: number
  revenue: number
  consumption_cost: number
}

export interface PnlCostBreakdown {
  consumption: number
  freight: number
  maintenance: number
}

export interface ContractPnl {
  contract: number
  units: string[]
  start: string | null
  end: string | null
  exam_volume: number
  revenue: number
  cost: number
  result: number
  cost_breakdown: PnlCostBreakdown
  by_service: PnlByServiceLine[]
}

// ─── Consumption ledger (ModelSerializer — cost_snapshot is a string) ───────

export interface ExamConsumptionRow {
  id: number
  unit: string
  service: number
  external_ref: string
  dicom_study: string | null
  source_warehouse: string | null
  performed_at: string
  cost_snapshot: string
  idempotency_key: string
  created_at: string
}

// ─── Material unit costs (ModelSerializer — unit_cost is a string) ──────────

export interface MaterialUnitCostRow {
  id: number
  material: string
  unit_cost: string
  created_at?: string
  updated_at?: string
}

export interface MaterialOption {
  id: string
  name: string
  unit_of_measure?: string
}

// A concession service, as returned by /api/v1/concession/services/. The P&L
// engine keys services by integer id; the catalog serializer may expose them
// as string or int, so name-resolution maps by String(id) defensively.
export interface ConcessionServiceLite {
  id: string | number
  code: string
  name: string
}

// ─── Formatting ─────────────────────────────────────────────────────────────

/** Integer volume with pt-BR grouping (e.g. 1.234). */
export function formatInt(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toLocaleString('pt-BR')
}

/** Timestamp → pt-BR date+time, or an em dash when absent/invalid. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('pt-BR')
}

/** First and last calendar day of the current month as YYYY-MM-DD. */
export function currentMonthRange(now: Date = new Date()): { start: string; end: string } {
  const y = now.getFullYear()
  const m = now.getMonth()
  const first = new Date(y, m, 1)
  const last = new Date(y, m + 1, 0)
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
      d.getDate()
    ).padStart(2, '0')}`
  return { start: iso(first), end: iso(last) }
}
