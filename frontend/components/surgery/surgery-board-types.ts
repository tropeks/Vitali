/**
 * C4 — Shared shapes/helpers for the Mapa Cirúrgico (surgical board).
 *
 * Mirrors the exact wire contract of the Centro Cirúrgico backend:
 *   GET /api/v1/surgical-cases/board/?date=&operating_room=&facility=
 *     → { date, rooms: [{ id, code, name, cases: [...] }] }
 * All ids are strings over the wire. The case `status` / `priority` enums are
 * copied from `backend/apps/emr/surgery_models.py` (SurgicalCase.Status /
 * Priority). Cancelled cases are excluded server-side; empty rooms come through
 * with `cases: []`.
 */

// ─── Board (GET /surgical-cases/board/) ──────────────────────────────────────

export interface BoardProcedure {
  tuss_code: string
  description: string
  quantity: number
}

export interface BoardParty {
  id: string
  name: string
}

export interface BoardCase {
  id: string
  patient: BoardParty
  surgeon: BoardParty
  scheduled_start: string | null
  scheduled_end: string | null
  status: string
  priority: string
  procedures: BoardProcedure[]
}

export interface BoardRoom {
  id: string
  code: string
  name: string
  cases: BoardCase[]
}

export interface SurgicalBoardResponse {
  date: string
  rooms: BoardRoom[]
}

// ─── Pickers (schedule flow) ─────────────────────────────────────────────────

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

/** A surgical case as returned by the CRUD list (SurgicalCaseSerializer). */
export interface SurgicalCaseDTO {
  id: string
  patient: string
  surgeon: string
  operating_room?: string | null
  scheduled_start?: string | null
  scheduled_end?: string | null
  priority: string
  status: string
}

/** A patient option for the create-case picker (`/patients/`). */
export interface PatientOption {
  id: string
  full_name: string
}

/** A professional (surgeon) option for the create-case picker (`/professionals/`). */
export interface ProfessionalOption {
  id: string
  user_name?: string | null
  council_number?: string | null
}

/** A facility option for the board filter (`/organization/facilities/`). */
export interface FacilityOption {
  id: string
  name: string
}

// ─── Status → accessible colour/label map ────────────────────────────────────

export interface CaseStatusMeta {
  label: string
  /** Block colouring (border + bg + text) for the case block. */
  blockClass: string
  /** Small pill colouring for the legend / status badge. */
  badgeClass: string
}

/** Situação do caso (SurgicalCase.Status). Cancelada is excluded from the board
 * server-side but is kept here for completeness. */
export const CASE_STATUS_META: Record<string, CaseStatusMeta> = {
  agendada: {
    label: 'Agendada',
    blockClass: 'border-slate-300 bg-slate-50 text-slate-800',
    badgeClass: 'border-slate-300 bg-slate-50 text-slate-700',
  },
  confirmada: {
    label: 'Confirmada',
    blockClass: 'border-blue-300 bg-blue-50 text-blue-900',
    badgeClass: 'border-blue-300 bg-blue-50 text-blue-800',
  },
  em_sala: {
    label: 'Em sala',
    blockClass: 'border-indigo-300 bg-indigo-50 text-indigo-900',
    badgeClass: 'border-indigo-300 bg-indigo-50 text-indigo-800',
  },
  em_andamento: {
    label: 'Em andamento',
    blockClass: 'border-amber-300 bg-amber-50 text-amber-900',
    badgeClass: 'border-amber-300 bg-amber-50 text-amber-800',
  },
  finalizada: {
    label: 'Finalizada',
    blockClass: 'border-green-300 bg-green-50 text-green-800',
    badgeClass: 'border-green-300 bg-green-50 text-green-800',
  },
  cancelada: {
    label: 'Cancelada',
    blockClass: 'border-red-300 bg-red-50 text-red-700',
    badgeClass: 'border-red-300 bg-red-50 text-red-700',
  },
}

export const FALLBACK_CASE_STATUS_META: CaseStatusMeta = {
  label: 'Situação desconhecida',
  blockClass: 'border-slate-300 bg-slate-50 text-slate-600',
  badgeClass: 'border-slate-300 bg-slate-50 text-slate-600',
}

export function caseStatusMeta(status: string): CaseStatusMeta {
  return CASE_STATUS_META[status] ?? { ...FALLBACK_CASE_STATUS_META, label: status }
}

// ─── Priority → accent map ───────────────────────────────────────────────────

export interface PriorityMeta {
  label: string
  /** Whether this priority deserves a visual accent on the block. */
  accent: boolean
  badgeClass: string
}

/** Prioridade (SurgicalCase.Priority). Urgência/Emergência get a left accent. */
export const PRIORITY_META: Record<string, PriorityMeta> = {
  eletiva: {
    label: 'Eletiva',
    accent: false,
    badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
  },
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

export function priorityMeta(priority: string): PriorityMeta {
  return (
    PRIORITY_META[priority] ?? {
      label: priority,
      accent: false,
      badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
    }
  )
}

export const PRIORITY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'eletiva', label: 'Eletiva' },
  { value: 'urgencia', label: 'Urgência' },
  { value: 'emergencia', label: 'Emergência' },
]

// ─── Case lifecycle helpers (which actions apply to a status) ─────────────────

/** A case can be confirmed only from `agendada`. */
export function canConfirmCase(status: string): boolean {
  return status === 'agendada'
}

/** A case can be rescheduled / cancelled while still before the room (pre-op). */
export function canRescheduleCase(status: string): boolean {
  return status === 'agendada' || status === 'confirmada'
}

export function canCancelCase(status: string): boolean {
  return status === 'agendada' || status === 'confirmada'
}

/** An unscheduled case (created but never slotted) — no times yet. */
export function isUnscheduled(c: SurgicalCaseDTO): boolean {
  return !c.scheduled_start
}

// ─── Formatting helpers ──────────────────────────────────────────────────────

/** HH:mm of an ISO datetime in pt-BR local time (else '—'). */
export function formatTime(value?: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "HH:mm – HH:mm" scheduled window (either side may be missing). */
export function formatWindow(start?: string | null, end?: string | null): string {
  if (!start && !end) return 'Sem horário'
  return `${formatTime(start)} – ${formatTime(end)}`
}

/** Long pt-BR date for the navigator header (e.g. "sexta, 24 de julho de 2026"). */
export function formatBoardDate(isoDate: string): string {
  // isoDate is a date-only string (YYYY-MM-DD); anchor at midday to dodge TZ shift.
  const d = new Date(`${isoDate}T12:00:00`)
  if (Number.isNaN(d.getTime())) return isoDate
  return d.toLocaleDateString('pt-BR', {
    weekday: 'long',
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  })
}

/** Add `delta` days to a YYYY-MM-DD string, returning a YYYY-MM-DD string. */
export function shiftDate(isoDate: string, delta: number): string {
  const d = new Date(`${isoDate}T12:00:00`)
  d.setDate(d.getDate() + delta)
  return toISODate(d)
}

/** Local YYYY-MM-DD for a Date (no TZ conversion). */
export function toISODate(date: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** Today as YYYY-MM-DD (local). */
export function todayISO(): string {
  return toISODate(new Date())
}

/** Local-datetime string (`YYYY-MM-DDTHH:mm`) for a datetime-local input default. */
export function localInput(date: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** datetime-local input value derived from an ISO datetime (for prefilling). */
export function isoToLocalInput(value?: string | null): string {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return localInput(d)
}
