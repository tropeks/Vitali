// Shared types + canonical badge/label maps for the concession (comodato)
// equipment fleet. Mirrors backend/apps/concession/asset_models.py TextChoices
// so labels match the server display strings exactly (pt-BR).

export type AssetStatus = 'ACTIVE' | 'IN_MAINTENANCE' | 'BACKUP' | 'WRITTEN_OFF'
export type AssetOwnership = 'OPERATOR' | 'CLIENT' | 'DOCTOR'
export type MovementType = 'DEPLOYMENT' | 'RETRIEVAL' | 'TRANSFER' | 'SWAP'

export interface Asset {
  id: string
  asset_tag: string
  name: string
  model: string
  serial_number: string
  status: AssetStatus
  ownership: AssetOwnership
  purchase_cost: string | null
  useful_life_months: number | null
  purchase_date: string | null
  current_location: string | null
  active: boolean
  monthly_depreciation: string
  created_at?: string
  updated_at?: string
}

export interface AssetMovement {
  id: string
  movement_type: MovementType
  asset: string
  from_facility: string | null
  to_facility: string | null
  swapped_with: string | null
  performed_by: string | null
  notes: string
  created_at: string
}

export interface FacilityOption {
  id: string
  name: string
}

export type Listish<T> = T[] | { results: T[]; count?: number }

export function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : (data?.results ?? [])
}

// ─── Badge / label maps ─────────────────────────────────────────────────────

interface BadgeMeta {
  label: string
  badgeClass: string
}

export const ASSET_STATUS_META: Record<AssetStatus, BadgeMeta> = {
  ACTIVE: { label: 'Ativo', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  IN_MAINTENANCE: {
    label: 'Em manutenção',
    badgeClass: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  },
  BACKUP: { label: 'Reserva', badgeClass: 'bg-blue-100 text-blue-800 border-blue-200' },
  WRITTEN_OFF: { label: 'Baixado', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' },
}

export const OWNERSHIP_LABEL: Record<AssetOwnership, string> = {
  OPERATOR: 'Operadora',
  CLIENT: 'Cliente',
  DOCTOR: 'Médico',
}

export const MOVEMENT_TYPE_LABEL: Record<MovementType, string> = {
  DEPLOYMENT: 'Implantação',
  RETRIEVAL: 'Recolhimento',
  TRANSFER: 'Transferência',
  SWAP: 'Troca',
}

export const ASSET_STATUS_OPTIONS = Object.entries(ASSET_STATUS_META).map(([value, meta]) => ({
  value: value as AssetStatus,
  label: meta.label,
}))

export const OWNERSHIP_OPTIONS = Object.entries(OWNERSHIP_LABEL).map(([value, label]) => ({
  value: value as AssetOwnership,
  label,
}))

export const MOVEMENT_TYPE_OPTIONS = Object.entries(MOVEMENT_TYPE_LABEL).map(([value, label]) => ({
  value: value as MovementType,
  label,
}))

// ─── Formatting helpers ─────────────────────────────────────────────────────

export function formatBRL(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  const num = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(num)) return '—'
  return num.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function facilityName(
  id: string | null | undefined,
  facilities: FacilityOption[]
): string {
  if (!id) return 'Armazém'
  return facilities.find((f) => f.id === id)?.name ?? '—'
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('pt-BR')
}
