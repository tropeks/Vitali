/**
 * H5 — Shared shapes/helpers for the Banco de Sangue / Agência Transfusional.
 *
 * Mirrors the exact wire contract of the hemoterapia backend (Sprints H1–H3):
 *   GET /api/v1/blood-bags/            → BloodBagDTO (estoque de bolsas)
 *   GET /api/v1/blood-components/      → BloodComponentDTO (catálogo)
 *   GET /api/v1/blood-donors/          → BloodDonorDTO
 *   POST /api/v1/blood-bag-serologies/ → BloodBagSerologyDTO (triagem RDC 34)
 *   GET /api/v1/transfusion-requests/  → TransfusionRequestDTO + crossmatches[]
 *
 * BloodBag / donor / request / crossmatch ids are UUID strings; the governed
 * `component` catalog pk is an integer. Enum values are copied verbatim from
 * `backend/apps/emr/bloodbank_models.py`, `blood_donor_models.py` and
 * `transfusion_models.py`.
 */

// ─── DRF list envelope ───────────────────────────────────────────────────────

export interface ListResponse<T> {
  results?: T[]
  count?: number
  next?: string | null
}

export function normalizeList<T>(payload: ListResponse<T> | T[] | null | undefined): T[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

// ─── DTOs ────────────────────────────────────────────────────────────────────

export type Abo = 'A' | 'B' | 'AB' | 'O'
export type RhFactor = 'positivo' | 'negativo'
export type SerologyStatus = 'quarentena' | 'liberada' | 'descartada'
export type StockStatus = 'disponivel' | 'reservada' | 'transfundida' | 'descartada' | 'vencida'
export type SerologyResult = 'nao_reagente' | 'reagente' | 'indeterminado'
export type Urgencia = 'rotina' | 'urgencia' | 'emergencia'
export type RequestStatus = 'solicitada' | 'reservada' | 'liberada' | 'transfundida' | 'cancelada'

export interface BloodComponentDTO {
  id: number
  code: string
  display: string
  system?: string
  version?: string
  active?: boolean
  default_validade_dias?: number | null
  context?: string
}

export interface BloodBagDTO {
  id: string
  identifier: string
  component: number
  component_code?: string
  component_display?: string
  abo: Abo
  rh_factor: RhFactor
  volume_ml: number
  collection_date: string
  expiry_date: string
  serology_status: SerologyStatus
  stock_status: StockStatus
  irradiada: boolean
  leucodepletada: boolean
  aferese: boolean
  lot?: string
  available: boolean
  created_at?: string
  updated_at?: string
}

export interface BloodDonorDTO {
  id: string
  full_name: string
  cpf?: string
  abo?: Abo | ''
  rh_factor?: RhFactor | ''
  birth_date?: string | null
  last_donation?: string | null
  apto: boolean
  notes?: string
  created_at?: string
  updated_at?: string
}

export interface BloodBagSerologyDTO {
  id: string
  bag: string
  hiv: SerologyResult
  hbsag: SerologyResult
  anti_hbc: SerologyResult
  anti_hcv: SerologyResult
  sifilis: SerologyResult
  chagas: SerologyResult
  htlv: SerologyResult
  all_non_reactive: boolean
  tested_at?: string
  notes?: string
}

export interface CrossMatchDTO {
  id: string
  request: string
  bag: string
  bag_identifier?: string
  abo_compativel: boolean
  rh_compativel: boolean
  crossmatch_resultado: 'compativel' | 'incompativel'
  compativel: boolean
  tested_at?: string
  notes?: string
}

export interface TransfusionRequestDTO {
  id: string
  patient: string
  encounter?: string | null
  admission?: string | null
  surgical_case?: string | null
  emergency_encounter?: string | null
  component: number
  component_code?: string
  component_display?: string
  quantidade: number
  indicacao: string
  cid?: string
  urgencia: Urgencia
  requester: string
  status: RequestStatus
  crossmatches: CrossMatchDTO[]
  created_at?: string
  updated_at?: string
}

// ─── Pickers ─────────────────────────────────────────────────────────────────

export interface PatientOption {
  id: string
  full_name: string
}

export interface ProfessionalOption {
  id: string
  user_name?: string | null
  council_number?: string | null
}

export interface EncounterOption {
  id: string
  encounter_type?: string
  status?: string
  start_time?: string | null
  created_at?: string | null
}

// ─── ABO / Rh presentation ───────────────────────────────────────────────────

/** '+' for positivo, '−' (minus sign) for negativo. */
export function rhSign(rh: RhFactor | '' | undefined): string {
  if (rh === 'positivo') return '+'
  if (rh === 'negativo') return '−'
  return ''
}

/** Compact blood-type label, e.g. "O+", "AB−". */
export function aboRhLabel(abo: Abo | '' | undefined, rh: RhFactor | '' | undefined): string {
  if (!abo) return '—'
  return `${abo}${rhSign(rh)}`
}

/** All 8 ABO/Rh groups, in the canonical stock-board order. */
export const ABO_RH_GROUPS: Array<{ abo: Abo; rh: RhFactor; label: string }> = (
  ['O', 'A', 'B', 'AB'] as Abo[]
).flatMap((abo) =>
  (['positivo', 'negativo'] as RhFactor[]).map((rh) => ({
    abo,
    rh,
    label: aboRhLabel(abo, rh),
  }))
)

export const ABO_OPTIONS: Array<{ value: Abo; label: string }> = [
  { value: 'A', label: 'A' },
  { value: 'B', label: 'B' },
  { value: 'AB', label: 'AB' },
  { value: 'O', label: 'O' },
]

export const RH_OPTIONS: Array<{ value: RhFactor; label: string }> = [
  { value: 'positivo', label: 'Positivo (+)' },
  { value: 'negativo', label: 'Negativo (−)' },
]

// ─── Status → accessible colour/label maps ───────────────────────────────────

export interface Meta {
  label: string
  badgeClass: string
}

export const SEROLOGY_STATUS_META: Record<SerologyStatus, Meta> = {
  quarentena: { label: 'Em quarentena', badgeClass: 'border-amber-300 bg-amber-50 text-amber-800' },
  liberada: { label: 'Liberada', badgeClass: 'border-green-300 bg-green-50 text-green-800' },
  descartada: { label: 'Descartada', badgeClass: 'border-red-300 bg-red-50 text-red-700' },
}

export const STOCK_STATUS_META: Record<StockStatus, Meta> = {
  disponivel: { label: 'Disponível', badgeClass: 'border-green-300 bg-green-50 text-green-800' },
  reservada: { label: 'Reservada', badgeClass: 'border-blue-300 bg-blue-50 text-blue-800' },
  transfundida: { label: 'Transfundida', badgeClass: 'border-slate-300 bg-slate-100 text-slate-700' },
  descartada: { label: 'Descartada', badgeClass: 'border-red-300 bg-red-50 text-red-700' },
  vencida: { label: 'Vencida', badgeClass: 'border-red-300 bg-red-50 text-red-700' },
}

export const URGENCIA_META: Record<Urgencia, Meta & { accent: boolean }> = {
  rotina: { label: 'Rotina', accent: false, badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  urgencia: {
    label: 'Urgência',
    accent: true,
    badgeClass: 'border-orange-300 bg-orange-50 text-orange-800',
  },
  emergencia: {
    label: 'Emergência',
    accent: true,
    badgeClass: 'border-red-300 bg-red-50 text-red-700',
  },
}

export const REQUEST_STATUS_META: Record<RequestStatus, Meta> = {
  solicitada: { label: 'Solicitada', badgeClass: 'border-slate-300 bg-slate-50 text-slate-700' },
  reservada: { label: 'Reservada', badgeClass: 'border-blue-300 bg-blue-50 text-blue-800' },
  liberada: { label: 'Liberada', badgeClass: 'border-indigo-300 bg-indigo-50 text-indigo-800' },
  transfundida: { label: 'Transfundida', badgeClass: 'border-green-300 bg-green-50 text-green-800' },
  cancelada: { label: 'Cancelada', badgeClass: 'border-red-300 bg-red-50 text-red-700' },
}

export function serologyStatusMeta(status: string): Meta {
  return (
    SEROLOGY_STATUS_META[status as SerologyStatus] ?? {
      label: status,
      badgeClass: 'border-slate-300 bg-slate-50 text-slate-600',
    }
  )
}

export function stockStatusMeta(status: string): Meta {
  return (
    STOCK_STATUS_META[status as StockStatus] ?? {
      label: status,
      badgeClass: 'border-slate-300 bg-slate-50 text-slate-600',
    }
  )
}

export function urgenciaMeta(urgencia: string): Meta & { accent: boolean } {
  return (
    URGENCIA_META[urgencia as Urgencia] ?? {
      label: urgencia,
      accent: false,
      badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
    }
  )
}

export function requestStatusMeta(status: string): Meta {
  return (
    REQUEST_STATUS_META[status as RequestStatus] ?? {
      label: status,
      badgeClass: 'border-slate-300 bg-slate-50 text-slate-600',
    }
  )
}

// ─── Request lifecycle helpers (which agency actions apply to a status) ──────

/** A bag can be reserved only for a still-solicitada request. */
export function canReserve(status: RequestStatus): boolean {
  return status === 'solicitada'
}

/** A reserved request can be liberated (bag confirmed for the patient). */
export function canLiberar(status: RequestStatus): boolean {
  return status === 'reservada'
}

/** A request can be cancelled from any non-terminal state. */
export function canCancel(status: RequestStatus): boolean {
  return status !== 'transfundida' && status !== 'cancelada'
}

// ─── RDC 34 serology panel ───────────────────────────────────────────────────

export const SEROLOGY_PANEL: Array<{ key: keyof Pick<
  BloodBagSerologyDTO,
  'hiv' | 'hbsag' | 'anti_hbc' | 'anti_hcv' | 'sifilis' | 'chagas' | 'htlv'
>; label: string }> = [
  { key: 'hiv', label: 'HIV' },
  { key: 'hbsag', label: 'HBsAg' },
  { key: 'anti_hbc', label: 'Anti-HBc' },
  { key: 'anti_hcv', label: 'Anti-HCV' },
  { key: 'sifilis', label: 'Sífilis' },
  { key: 'chagas', label: 'Doença de Chagas' },
  { key: 'htlv', label: 'HTLV I/II' },
]

export const SEROLOGY_RESULT_OPTIONS: Array<{ value: SerologyResult; label: string }> = [
  { value: 'nao_reagente', label: 'Não reagente' },
  { value: 'reagente', label: 'Reagente' },
  { value: 'indeterminado', label: 'Indeterminado' },
]

export const URGENCIA_OPTIONS: Array<{ value: Urgencia; label: string }> = [
  { value: 'rotina', label: 'Rotina' },
  { value: 'urgencia', label: 'Urgência' },
  { value: 'emergencia', label: 'Emergência' },
]

export const REQUEST_STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Todas as situações' },
  { value: 'solicitada', label: 'Solicitadas' },
  { value: 'reservada', label: 'Reservadas' },
  { value: 'liberada', label: 'Liberadas' },
  { value: 'transfundida', label: 'Transfundidas' },
  { value: 'cancelada', label: 'Canceladas' },
]

// ─── Date / expiry helpers ───────────────────────────────────────────────────

export function todayISO(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** pt-BR short date (dd/mm/aaaa) for a YYYY-MM-DD (else '—'). */
export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(`${value}T12:00:00`)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/** Whole days from `today` until `expiry` (negative = already expired). */
export function daysUntil(expiry?: string | null, today: string = todayISO()): number | null {
  if (!expiry) return null
  const a = new Date(`${expiry}T12:00:00`)
  const b = new Date(`${today}T12:00:00`)
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null
  return Math.round((a.getTime() - b.getTime()) / 86_400_000)
}

export function isExpired(bag: Pick<BloodBagDTO, 'expiry_date' | 'stock_status'>, today?: string): boolean {
  if (bag.stock_status === 'vencida') return true
  const d = daysUntil(bag.expiry_date, today)
  return d !== null && d < 0
}

/** A still-valid bag whose validade is within `withinDays` (default 7). */
export function isExpiringSoon(
  bag: Pick<BloodBagDTO, 'expiry_date' | 'stock_status'>,
  withinDays = 7,
  today?: string
): boolean {
  if (bag.stock_status === 'vencida') return false
  const d = daysUntil(bag.expiry_date, today)
  return d !== null && d >= 0 && d <= withinDays
}

export interface ExpiryMeta {
  tone: 'ok' | 'soon' | 'expired'
  label: string
  className: string
}

export function expiryMeta(bag: BloodBagDTO, today?: string): ExpiryMeta {
  if (isExpired(bag, today)) {
    return { tone: 'expired', label: 'Vencida', className: 'text-red-700 font-semibold' }
  }
  if (isExpiringSoon(bag, 7, today)) {
    const d = daysUntil(bag.expiry_date, today)
    return {
      tone: 'soon',
      label: d === 0 ? 'Vence hoje' : `Vence em ${d}d`,
      className: 'text-amber-700 font-semibold',
    }
  }
  return { tone: 'ok', label: `Val. ${formatDate(bag.expiry_date)}`, className: 'text-neu-inkMuted' }
}

// ─── KPI aggregation ─────────────────────────────────────────────────────────

export interface StockSummary {
  total: number
  disponiveis: number
  quarentena: number
  vencidas: number
  aVencer: number
  reservadas: number
  /** available (dispensable) count per ABO/Rh group label, e.g. { 'O+': 3 }. */
  byAboRh: Record<string, number>
}

export function summarizeStock(bags: BloodBagDTO[], today?: string): StockSummary {
  const summary: StockSummary = {
    total: bags.length,
    disponiveis: 0,
    quarentena: 0,
    vencidas: 0,
    aVencer: 0,
    reservadas: 0,
    byAboRh: {},
  }
  for (const bag of bags) {
    if (bag.serology_status === 'quarentena') summary.quarentena += 1
    if (bag.stock_status === 'reservada') summary.reservadas += 1
    if (isExpired(bag, today)) {
      summary.vencidas += 1
      continue
    }
    if (bag.available) {
      summary.disponiveis += 1
      const key = aboRhLabel(bag.abo, bag.rh_factor)
      summary.byAboRh[key] = (summary.byAboRh[key] ?? 0) + 1
      if (isExpiringSoon(bag, 7, today)) summary.aVencer += 1
    }
  }
  return summary
}

/** Friendly pt-BR message for a hemoterapia ApiError body ({detail: string|string[]}). */
export function apiErrorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (Array.isArray(detail)) return detail.join(' ')
    if (typeof detail === 'string') return detail
  }
  return fallback
}
