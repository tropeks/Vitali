// Shared types + canonical badge/label maps for the concession logistics
// chain (requisição → separação → despacho → entrega). Mirrors the pt-BR
// TextChoices in backend/apps/concession/logistics_models.py so labels match
// the server display strings exactly.

export type RequisitionStatus =
  | 'draft'
  | 'submitted'
  | 'approved'
  | 'fulfilled'
  | 'cancelled'
export type PickListStatus = 'pending' | 'picking' | 'picked'
export type DispatchStatus = 'pending' | 'in_transit' | 'delivered'
export type DiscrepancyType = 'missing' | 'damaged' | 'extra'

export interface BadgeMeta {
  label: string
  badgeClass: string
}

// ─── Domain shapes (subset of the serializers we render) ─────────────────────

export interface RequisitionItem {
  id?: string
  material: string
  quantity: string | number
}

export interface SupplyRequisition {
  id: string
  requesting_facility: string
  status: RequisitionStatus
  requested_by?: string | null
  notes: string
  items: RequisitionItem[]
  submitted_at?: string | null
  approved_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface PickItem {
  id: string
  requisition_item: string
  material: string
  source_stock_item: string | null
  quantity: string | number
  picked_qty: string | number
  is_picked: boolean
  picked_at?: string | null
}

export interface PickList {
  id: string
  requisition: string
  status: PickListStatus
  items: PickItem[]
  started_at?: string | null
  completed_at?: string | null
  created_at?: string
}

export interface DispatchItem {
  id: string
  material: string
  source_stock_item: string | null
  quantity: string | number
  received_qty: string | number | null
}

export interface Dispatch {
  id: string
  manifest_code: string
  pick_list: string
  source_warehouse: string
  destination_facility?: string | null
  destination_warehouse?: string | null
  status: DispatchStatus
  items: DispatchItem[]
  freight_cost?: string | null
  shipped_at?: string | null
  delivered_at?: string | null
  created_at?: string
}

export interface ProofOfDelivery {
  id: string
  dispatch: string
  received_by: string
  signature_ref: string
  geo_lat: string | null
  geo_lng: string | null
  delivered_at: string
  captured_by?: string | null
  created_at?: string
}

export interface DispatchDiscrepancy {
  id: string
  dispatch?: string
  dispatch_item: string | null
  type: DiscrepancyType
  material: string
  quantity: string | number
  notes: string
}

// ─── Option shapes for selects ───────────────────────────────────────────────

export interface FacilityOption {
  id: string
  name: string
}

export interface MaterialOption {
  id: string
  name: string
  unit_of_measure?: string
}

export interface WarehouseOption {
  id: string
  name: string
  code?: string
}

export interface StockItemOption {
  id: string
  material: string
  material_name?: string
  warehouse?: string
  quantity?: string | number
  lot_number?: string
}

// ─── API endpoints ───────────────────────────────────────────────────────────

export const LOGISTICS_ENDPOINTS = {
  requisitions: '/api/v1/concession/supply-requisitions/',
  pickLists: '/api/v1/concession/pick-lists/',
  dispatches: '/api/v1/concession/dispatches/',
  proofs: '/api/v1/concession/proof-of-deliveries/',
  discrepancies: '/api/v1/concession/dispatch-discrepancies/',
  facilities: '/api/v1/organization/facilities/',
  materials: '/api/v1/pharmacy/materials/',
  warehouses: '/api/v1/pharmacy/warehouses/',
  stockItems: '/api/v1/pharmacy/stock/items/',
} as const

// ─── Listish unwrap (array or {results,count}) ───────────────────────────────

export type Listish<T> = T[] | { results: T[]; count?: number }

export function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : (data?.results ?? [])
}

// ─── Badge / label maps ──────────────────────────────────────────────────────

export const REQUISITION_STATUS_META: Record<RequisitionStatus, BadgeMeta> = {
  draft: { label: 'Rascunho', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' },
  submitted: { label: 'Enviada', badgeClass: 'bg-blue-100 text-blue-800 border-blue-200' },
  approved: { label: 'Aprovada', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  fulfilled: { label: 'Atendida', badgeClass: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
  cancelled: { label: 'Cancelada', badgeClass: 'bg-red-100 text-red-700 border-red-200' },
}

export const PICKLIST_STATUS_META: Record<PickListStatus, BadgeMeta> = {
  pending: { label: 'Pendente', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' },
  picking: { label: 'Em separação', badgeClass: 'bg-yellow-100 text-yellow-800 border-yellow-200' },
  picked: { label: 'Separada', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
}

export const DISPATCH_STATUS_META: Record<DispatchStatus, BadgeMeta> = {
  pending: { label: 'Pendente', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' },
  in_transit: { label: 'Em trânsito', badgeClass: 'bg-blue-100 text-blue-800 border-blue-200' },
  delivered: { label: 'Entregue', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
}

export const DISCREPANCY_TYPE_META: Record<DiscrepancyType, BadgeMeta> = {
  missing: { label: 'Faltante', badgeClass: 'bg-red-100 text-red-700 border-red-200' },
  damaged: { label: 'Avariado', badgeClass: 'bg-orange-100 text-orange-800 border-orange-200' },
  extra: { label: 'Excedente', badgeClass: 'bg-purple-100 text-purple-800 border-purple-200' },
}

export const DISCREPANCY_TYPE_OPTIONS = (
  Object.entries(DISCREPANCY_TYPE_META) as [DiscrepancyType, BadgeMeta][]
).map(([value, meta]) => ({ value, label: meta.label }))

// Fallback meta so an unknown server status never crashes a badge.
export function metaOr(map: Record<string, BadgeMeta>, key: string): BadgeMeta {
  return map[key] ?? { label: key, badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' }
}

// ─── Formatting + lookup helpers ─────────────────────────────────────────────

export function nameFrom<T extends { id: string; name?: string }>(
  id: string | null | undefined,
  options: T[],
  fallback = '—'
): string {
  if (!id) return fallback
  return options.find((o) => o.id === id)?.name ?? id
}

export function materialName(id: string | null | undefined, materials: MaterialOption[]): string {
  if (!id) return '—'
  return materials.find((m) => m.id === id)?.name ?? id
}

export function stockLabel(
  item: StockItemOption,
  warehouses: WarehouseOption[] = []
): string {
  const parts = [item.material_name ?? item.material]
  const wh = warehouses.find((w) => w.id === item.warehouse)?.name
  if (wh) parts.push(wh)
  if (item.quantity != null) parts.push(`saldo ${item.quantity}`)
  if (item.lot_number) parts.push(`lote ${item.lot_number}`)
  return parts.join(' · ')
}

export function formatQty(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  const num = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(num)) return String(value)
  return num.toLocaleString('pt-BR', { maximumFractionDigits: 3 })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('pt-BR')
}
