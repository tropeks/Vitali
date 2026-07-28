// Shared types + canonical badge/label maps for concession (concessão)
// maintenance tickets. Mirrors backend/apps/concession/serializers_assets.py
// MaintenanceTicketSerializer so labels match server display strings.
//
// Formatting + list-unwrap helpers are reused from assetMeta so there is a
// single source of truth for BRL/date rendering across the concession module.

export {
  unwrap,
  formatBRL,
  formatDate,
  type FacilityOption,
  type Listish,
} from './assetMeta'

import { facilityName as assetFacilityName, type FacilityOption } from './assetMeta'

export type MaintenanceTicketStatus = 'OPEN' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'

export interface MaintenanceTicket {
  id: string
  asset: string
  facility: string | null
  description: string
  status: MaintenanceTicketStatus
  cost: string | null
  evidence_url: string
  resolution: string
  reported_by: string | null
  assigned_to: string | null
  started_at: string | null
  completed_at: string | null
  created_at?: string
  updated_at?: string
}

// Minimal shape of an EquipmentAsset needed to label the asset select /
// ticket cards — avoids importing the full Asset interface's optional
// depreciation fields.
export interface AssetOption {
  id: string
  asset_tag: string
  name: string
  model?: string
}

export const MAINTENANCE_ENDPOINTS = {
  tickets: '/api/v1/concession/maintenance-tickets/',
  assets: '/api/v1/concession/assets/',
  facilities: '/api/v1/organization/facilities/',
} as const

// ─── Badge / label maps ─────────────────────────────────────────────────────

interface BadgeMeta {
  label: string
  badgeClass: string
}

export const MAINTENANCE_STATUS_META: Record<MaintenanceTicketStatus, BadgeMeta> = {
  OPEN: { label: 'Aberto', badgeClass: 'bg-red-100 text-red-800 border-red-200' },
  IN_PROGRESS: {
    label: 'Em andamento',
    badgeClass: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  },
  COMPLETED: { label: 'Concluído', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  CANCELLED: { label: 'Cancelado', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' },
}

export const MAINTENANCE_STATUS_OPTIONS = Object.entries(MAINTENANCE_STATUS_META).map(
  ([value, meta]) => ({ value: value as MaintenanceTicketStatus, label: meta.label })
)

// Kanban column order — one column per ticket status, pt-BR headers.
export const MAINTENANCE_COLUMNS: { status: MaintenanceTicketStatus; title: string }[] = [
  { status: 'OPEN', title: 'Abertos' },
  { status: 'IN_PROGRESS', title: 'Em andamento' },
  { status: 'COMPLETED', title: 'Concluídos' },
  { status: 'CANCELLED', title: 'Cancelados' },
]

// ─── Formatting helpers ─────────────────────────────────────────────────────

export function assetLabel(id: string | null | undefined, assets: AssetOption[]): string {
  if (!id) return '—'
  const asset = assets.find((a) => a.id === id)
  if (!asset) return '—'
  return asset.name ? `${asset.asset_tag} — ${asset.name}` : asset.asset_tag
}

export function facilityName(
  id: string | null | undefined,
  facilities: FacilityOption[]
): string {
  if (!id) return '—'
  return assetFacilityName(id, facilities)
}
