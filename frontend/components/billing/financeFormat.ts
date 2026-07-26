/**
 * Shared money/date formatters + backend row types for the treasury surfaces
 * (Contas a pagar / a receber / Tesouraria). Amounts arrive as decimal STRINGS
 * from DRF; we render via toLocaleString for pt-BR BRL display.
 */

export const formatBRL = (value: string | number | null | undefined): string =>
  Number(value ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

export const formatDate = (value: string | null | undefined): string => {
  if (!value) return '—'
  // Backend DateField serializes as YYYY-MM-DD; pin to local midnight so the
  // day never shifts across timezones.
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleDateString('pt-BR')
}

export interface Payable {
  id: string
  external_id: string
  description: string
  category: string
  amount: string
  due_date: string
  paid_at: string | null
  status: 'planned' | 'approved' | 'paid' | 'cancelled' | string
  notes: string
  created_at: string
  updated_at: string
}

export interface Receivable {
  id: string
  guide_number: string | null
  patient_name: string | null
  provider_name: string | null
  amount: string
  due_date: string | null
  received_at: string | null
  status: 'expected' | 'billed' | 'partial' | 'received' | 'overdue' | 'contested' | string
  notes: string
  created_at: string
  updated_at: string
}

export interface CashFlowEntry {
  id: string
  external_id: string
  description: string
  kind: 'inflow' | 'outflow' | string
  amount: string
  due_date: string
  realized_at: string | null
  category: string
  cost_center: string
  status: 'forecast' | 'realized' | 'cancelled' | string
  created_at: string
}
