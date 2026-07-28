// Shared types + canonical badge/label maps for concession (concessão)
// contracts, service prices, recipes and the service catalog. Mirrors
// backend/apps/concession serializers so labels match server display strings.
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

export type ContractStatus = 'ACTIVE' | 'EXPIRED' | 'TERMINATED'

export interface ConcessionContract {
  id: string
  name: string
  client_name: string
  client: string | null
  units: string[]
  monthly_value: string | null
  start_date: string | null
  end_date: string | null
  status: ContractStatus
  created_at?: string
  updated_at?: string
}

export interface ConcessionService {
  id: string
  code: string
  name: string
  modality: string
  tuss_code: string
  active: boolean
}

export interface ContractPrice {
  id: string
  contract: string | null
  unit: string | null
  service: string
  price: string
  is_billable: boolean
  billable_revenue?: string | null
}

export interface ServiceRecipe {
  id: string
  service: string
  material: string
  quantity: string
}

export interface MaterialOption {
  id: string
  name: string
  unit_of_measure?: string
}

// ─── Badge / label maps ─────────────────────────────────────────────────────

interface BadgeMeta {
  label: string
  badgeClass: string
}

export const CONTRACT_STATUS_META: Record<ContractStatus, BadgeMeta> = {
  ACTIVE: { label: 'Ativo', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  EXPIRED: { label: 'Expirado', badgeClass: 'bg-yellow-100 text-yellow-800 border-yellow-200' },
  TERMINATED: {
    label: 'Encerrado',
    badgeClass: 'bg-slate-100 text-slate-600 border-slate-200',
  },
}

export const CONTRACT_STATUS_OPTIONS = Object.entries(CONTRACT_STATUS_META).map(
  ([value, meta]) => ({ value: value as ContractStatus, label: meta.label })
)

export function contractStatusMeta(status: string): BadgeMeta {
  return (
    CONTRACT_STATUS_META[status as ContractStatus] ?? {
      label: status,
      badgeClass: 'bg-slate-100 text-slate-600 border-slate-200',
    }
  )
}
