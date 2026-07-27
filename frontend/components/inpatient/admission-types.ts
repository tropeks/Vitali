/**
 * ADT / internação (L5) — shared types and enum→label maps for the inpatient
 * admission surface on the patient chart.
 *
 * Shapes mirror `backend/apps/emr/serializers_adt.py` EXACTLY. Note the
 * important API-shape reality: `AdmissionSerializer` returns *pk ids* for
 * `current_bed`, `admitting_professional` and `attending_professional` (not
 * nested objects), so the panel enriches them client-side via `/beds/board/`
 * and `/professionals/{id}/`. All ids are strings.
 */

/** DRF paginated envelope, tolerated alongside a bare array. */
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

/** Admission (internação) — pk-based FKs, exactly as the serializer emits. */
export interface Admission {
  id: string
  patient: string
  admitting_professional: string
  attending_professional: string
  current_bed?: string | null
  encounter?: string | null
  admission_source: string
  admission_datetime: string
  expected_discharge_datetime?: string | null
  actual_discharge_datetime?: string | null
  disposition?: string | null
  status: string
  created_at?: string | null
  updated_at?: string | null
}

/** Append-only ADT event (read-only surface). */
export interface AdmissionEvent {
  id: string
  admission: string
  event_type: string
  from_bed?: string | null
  to_bed?: string | null
  actor?: string | null
  reason?: string | null
  created_at?: string | null
}

/** A free bed option for the admit picker (`/beds/?status=livre`). */
export interface BedOption {
  id: string
  identifier: string
  unit?: string | null
  status: string
}

/** A professional option for the admit pickers (`/professionals/?search=`). */
export interface ProfessionalOption {
  id: string
  user_name?: string | null
  specialty?: string | null
  council_number?: string | null
}

/** `/beds/board/` tree — used to resolve bed identifier + unit name for a stay. */
export interface BoardBed {
  id: string
  identifier: string
  status: string
  patient?: { id: string; name: string } | null
}
export interface BoardRoom {
  id: string
  name: string
  beds: BoardBed[]
}
export interface BoardUnit {
  id: string
  code: string
  name: string
  rooms: BoardRoom[]
}
export interface BoardResponse {
  units: BoardUnit[]
}

// ─── enum → label maps (mirror adt_models TextChoices) ───────────────────────

export const ADMISSION_SOURCE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'emergencia', label: 'Emergência' },
  { value: 'ambulatorio', label: 'Ambulatório' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'centro_cirurgico', label: 'Centro cirúrgico' },
  { value: 'outro', label: 'Outro' },
]

export const DISPOSITION_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'alta_melhorada', label: 'Alta melhorada' },
  { value: 'alta_a_pedido', label: 'Alta a pedido' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'obito', label: 'Óbito' },
  { value: 'evasao', label: 'Evasão' },
  { value: 'outro', label: 'Outro' },
]

export const EVENT_TYPE_META: Record<string, { label: string; badgeClass: string }> = {
  admit: { label: 'Admissão', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
  transfer: { label: 'Transferência', badgeClass: 'border-blue-200 bg-blue-50 text-blue-700' },
  discharge: { label: 'Alta', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  cancel: { label: 'Cancelamento', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
}

export const ADMISSION_STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  admitted: { label: 'Internado', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
  discharged: { label: 'Alta', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' },
  cancelled: { label: 'Cancelada', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
}

export function labelOf(
  options: Array<{ value: string; label: string }>,
  value?: string | null,
): string {
  if (!value) return '—'
  return options.find((option) => option.value === value)?.label ?? value
}

/** Local-datetime string (`YYYY-MM-DDTHH:mm`) for a datetime-local default of now. */
export function nowLocalInput(date: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** pt-BR date/time formatter shared by the panel + timeline. */
export function formatDateTime(value?: string | null): string {
  if (!value) return 'Não informado'
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Length of stay from `admission_datetime` to `end` (default now), as a compact
 * pt-BR string ("3d 4h", "5h 20min", "12min"). Never negative.
 */
export function formatLOS(startISO?: string | null, endISO?: string | null): string {
  if (!startISO) return '—'
  const start = new Date(startISO).getTime()
  const end = endISO ? new Date(endISO).getTime() : Date.now()
  let ms = end - start
  if (!Number.isFinite(ms) || ms < 0) ms = 0
  const totalMinutes = Math.floor(ms / 60000)
  const days = Math.floor(totalMinutes / 1440)
  const hours = Math.floor((totalMinutes % 1440) / 60)
  const minutes = totalMinutes % 60
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}min`
  return `${minutes}min`
}
