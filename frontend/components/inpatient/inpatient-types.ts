/**
 * L4 — Shared shapes/helpers for the Painel de Internação (bed-map + census).
 *
 * Mirrors the exact wire contracts of the ADT backend:
 *   - GET /api/v1/beds/board/       → { units: [...] } (units → rooms → beds)
 *   - GET /api/v1/admissions/census/ → { occupancy: [...], census: [...] }
 * All ids are strings over the wire. Bed status enum + Admission disposition /
 * source choices are copied from `backend/apps/emr/adt_models.py`.
 */

import type { OperationalTone } from '@/lib/operational-ui'

// ─── Bed-board (GET /beds/board/) ────────────────────────────────────────────

export interface BedOccupant {
  id: string
  name: string
}

export interface BoardBed {
  id: string
  identifier: string
  status: string
  /** Present (id/name) only when the bed is occupied by an active admission. */
  patient?: BedOccupant | null
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

// ─── Census / occupancy (GET /admissions/census/) ────────────────────────────

export interface CensusUnitRef {
  id: string
  code: string
  name: string
}

export interface OccupancyRow {
  unit: CensusUnitRef
  total_beds: number
  status_counts: Record<string, number>
  operational_beds: number
  occupied: number
  /** Fraction 0..1 — `occupied / operational_beds`. Format with formatPercent. */
  occupancy_rate: number
}

export interface CensusRow {
  admission_id: string
  patient: { id: string; name: string }
  bed: { id: string; identifier: string }
  unit: CensusUnitRef
  admission_datetime: string
  los_hours: number
}

export interface CensusResponse {
  occupancy: OccupancyRow[]
  census: CensusRow[]
}

// ─── Bed status → accessible colour/label map ────────────────────────────────

export interface BedStatusMeta {
  label: string
  /** Cell colouring (border + bg + text) for the bed-map. */
  cellClass: string
  tone: OperationalTone
}

/** Situação do leito (Bed.Status em adt_models). Livre=verde, Ocupado=azul,
 * Higienização=amarelo, Reservado=índigo, Bloqueado=cinza, Interditado=vermelho. */
export const BED_STATUS_META: Record<string, BedStatusMeta> = {
  livre: {
    label: 'Livre',
    cellClass: 'border-green-300 bg-green-50 text-green-800',
    tone: 'success',
  },
  ocupado: {
    label: 'Ocupado',
    cellClass: 'border-blue-300 bg-blue-50 text-blue-900',
    tone: 'info',
  },
  higienizacao: {
    label: 'Em higienização',
    cellClass: 'border-yellow-300 bg-yellow-50 text-yellow-800',
    tone: 'attention',
  },
  reservado: {
    label: 'Reservado',
    cellClass: 'border-indigo-300 bg-indigo-50 text-indigo-800',
    tone: 'info',
  },
  bloqueado: {
    label: 'Bloqueado',
    cellClass: 'border-slate-300 bg-slate-100 text-slate-600',
    tone: 'neutral',
  },
  interditado: {
    label: 'Interditado',
    cellClass: 'border-red-300 bg-red-50 text-red-700',
    tone: 'critical',
  },
}

export const FALLBACK_BED_STATUS_META: BedStatusMeta = {
  label: 'Situação desconhecida',
  cellClass: 'border-slate-300 bg-slate-50 text-slate-600',
  tone: 'neutral',
}

export function bedStatusMeta(status: string): BedStatusMeta {
  return BED_STATUS_META[status] ?? { ...FALLBACK_BED_STATUS_META, label: status }
}

/** A bed a patient could be transferred INTO — i.e. currently livre. */
export function isFreeBed(bed: BoardBed): boolean {
  return bed.status === 'livre'
}

// ─── Admission choices (Admission.Disposition / AdmissionSource) ──────────────

export interface ChoiceOption {
  value: string
  label: string
}

export const DISPOSITION_OPTIONS: ChoiceOption[] = [
  { value: 'alta_melhorada', label: 'Alta melhorada' },
  { value: 'alta_a_pedido', label: 'Alta a pedido' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'obito', label: 'Óbito' },
  { value: 'evasao', label: 'Evasão' },
  { value: 'outro', label: 'Outro' },
]

export const ADMISSION_SOURCE_OPTIONS: ChoiceOption[] = [
  { value: 'emergencia', label: 'Emergência' },
  { value: 'ambulatorio', label: 'Ambulatório' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'centro_cirurgico', label: 'Centro cirúrgico' },
  { value: 'outro', label: 'Outro' },
]

// ─── Formatting helpers ──────────────────────────────────────────────────────

/** LOS is reported in whole hours; render coarse (e.g. "3d 4h", "5h", "0h"). */
export function formatLos(hours: number | null | undefined): string {
  if (hours == null || hours < 0) return '—'
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  const rest = hours % 24
  return rest === 0 ? `${days}d` : `${days}d ${rest}h`
}

/** occupancy_rate is a 0..1 fraction; render as a rounded percent (e.g. "75%"). */
export function formatPercent(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return '—'
  return `${Math.round(rate * 100)}%`
}
