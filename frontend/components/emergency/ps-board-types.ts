/**
 * E4 — Shared shapes/helpers for the Painel de Pronto-Socorro (fila Manchester).
 *
 * Mirrors the exact wire contract of the PS/Emergência backend:
 *   GET /api/v1/emergency-encounters/board/
 *     → { queue: [row…], counts: {vermelho,…,azul}, overdue, unclassified, total }
 * All ids are strings over the wire. The acuity levels + Manchester tempo-alvo
 * minutes are copied from `backend/apps/core/manchester_catalog_models.py`
 * (AcuityLevel / ACUITY_TARGET_MINUTES); mode_of_arrival / status / disposition
 * enums from `backend/apps/emr/emergency_models.py`.
 */

// ─── Board (GET /emergency-encounters/board/) ────────────────────────────────

export interface QueueParty {
  id: string
  name: string
}

export interface QueueRow {
  boletim_id: string
  patient: QueueParty
  status: string
  mode_of_arrival: string
  chief_complaint: string
  arrival_at: string
  waited_minutes: number
  /** null while the boletim is not yet classified (aguardando_classificacao). */
  acuity_level: string | null
  /** null while unclassified; else the Manchester tempo-alvo (min). */
  target_minutes: number | null
  overdue: boolean
}

export interface BoardCounts {
  vermelho: number
  laranja: number
  amarelo: number
  verde: number
  azul: number
}

export interface BoardResponse {
  queue: QueueRow[]
  counts: BoardCounts
  overdue: number
  unclassified: number
  total: number
}

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

// ─── Picker option shapes ────────────────────────────────────────────────────

/** A patient option for the abrir-boletim picker (`/patients/?search=`). */
export interface PatientOption {
  id: string
  full_name: string
}

/** A professional option (`/professionals/?search=`). */
export interface ProfessionalOption {
  id: string
  user_name?: string | null
  council_number?: string | null
}

/** A free bed for the internação disposition (`/beds/?status=livre`). */
export interface BedOption {
  id: string
  identifier: string
}

/** A Manchester fluxograma (`/manchester-flowcharts/?q=`). */
export interface FlowchartOption {
  id: string
  code: string
  display: string
}

/** A Manchester discriminador (`/manchester-discriminators/?flowchart=<pk>`). */
export interface DiscriminatorOption {
  id: string
  flowchart: string
  code: string
  name: string
  description?: string
  acuity_level: string
  target_minutes: number
  is_general?: boolean
  active?: boolean
}

// ─── Acuidade → accessible colour/label map (Manchester) ─────────────────────

export interface AcuityMeta {
  /** Short chip label (ex.: 'Vermelho'). */
  label: string
  /** Full pt-BR label (ex.: 'Vermelho (emergência)'). */
  fullLabel: string
  /** Row colouring (border + bg + text). */
  rowClass: string
  /** Small pill colouring for the legend / counts header. */
  badgeClass: string
  /** Left accent bar colour for the queue row. */
  accentClass: string
  /** Manchester tempo-alvo de atendimento (min). */
  targetMinutes: number
}

/** Nível de acuidade (AcuityLevel). Ordered vermelho → azul (most → least urgent). */
export const ACUITY_META: Record<string, AcuityMeta> = {
  vermelho: {
    label: 'Vermelho',
    fullLabel: 'Vermelho (emergência)',
    rowClass: 'border-red-300 bg-red-50 text-red-900',
    badgeClass: 'border-red-300 bg-red-100 text-red-800',
    accentClass: 'bg-red-500',
    targetMinutes: 0,
  },
  laranja: {
    label: 'Laranja',
    fullLabel: 'Laranja (muito urgente)',
    rowClass: 'border-orange-300 bg-orange-50 text-orange-900',
    badgeClass: 'border-orange-300 bg-orange-100 text-orange-800',
    accentClass: 'bg-orange-500',
    targetMinutes: 10,
  },
  amarelo: {
    label: 'Amarelo',
    fullLabel: 'Amarelo (urgente)',
    rowClass: 'border-amber-300 bg-amber-50 text-amber-900',
    badgeClass: 'border-amber-300 bg-amber-100 text-amber-800',
    accentClass: 'bg-amber-400',
    targetMinutes: 60,
  },
  verde: {
    label: 'Verde',
    fullLabel: 'Verde (pouco urgente)',
    rowClass: 'border-green-300 bg-green-50 text-green-900',
    badgeClass: 'border-green-300 bg-green-100 text-green-800',
    accentClass: 'bg-green-500',
    targetMinutes: 120,
  },
  azul: {
    label: 'Azul',
    fullLabel: 'Azul (não urgente)',
    rowClass: 'border-blue-300 bg-blue-50 text-blue-900',
    badgeClass: 'border-blue-300 bg-blue-100 text-blue-800',
    accentClass: 'bg-blue-500',
    targetMinutes: 240,
  },
}

/** Neutral meta for a boletim que ainda não foi classificado (acuity_level null). */
export const UNCLASSIFIED_META: AcuityMeta = {
  label: 'Aguardando classificação',
  fullLabel: 'Aguardando classificação',
  rowClass: 'border-slate-300 bg-slate-50 text-slate-700',
  badgeClass: 'border-slate-300 bg-slate-100 text-slate-700',
  accentClass: 'bg-slate-400',
  targetMinutes: 0,
}

/** Acuidade ordenada (vermelho → azul) para o cabeçalho de contagens / legenda. */
export const ACUITY_ORDER: Array<keyof BoardCounts> = [
  'vermelho',
  'laranja',
  'amarelo',
  'verde',
  'azul',
]

/** Meta for an acuity level (null / unknown → the neutral unclassified meta). */
export function acuityMeta(level: string | null | undefined): AcuityMeta {
  if (!level) return UNCLASSIFIED_META
  return ACUITY_META[level] ?? { ...UNCLASSIFIED_META, label: level, fullLabel: level }
}

// ─── Enum option lists (mode_of_arrival / status / disposition) ──────────────

export interface ChoiceOption {
  value: string
  label: string
}

/** Meio de chegada (EmergencyEncounter.ModeOfArrival). */
export const MODE_OF_ARRIVAL_OPTIONS: ChoiceOption[] = [
  { value: 'ambulante', label: 'Ambulante' },
  { value: 'cadeira_rodas', label: 'Cadeira de rodas' },
  { value: 'maca', label: 'Maca' },
  { value: 'ambulancia', label: 'Ambulância' },
  { value: 'viatura_pm', label: 'Viatura (PM/SAMU)' },
  { value: 'outro', label: 'Outro' },
]

export function modeOfArrivalLabel(value: string): string {
  return MODE_OF_ARRIVAL_OPTIONS.find((o) => o.value === value)?.label ?? value
}

/** Situação do boletim (EmergencyEncounter.Status). */
export const STATUS_LABELS: Record<string, string> = {
  aguardando_classificacao: 'Aguardando classificação',
  classificado: 'Classificado',
  em_atendimento: 'Em atendimento',
  encerrado: 'Encerrado',
}

export function statusLabel(value: string): string {
  return STATUS_LABELS[value] ?? value
}

/** Desfecho do atendimento (EmergencyEncounter.Disposition). */
export const DISPOSITION_OPTIONS: ChoiceOption[] = [
  { value: 'alta', label: 'Alta' },
  { value: 'internacao', label: 'Internação' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'obito', label: 'Óbito' },
  { value: 'evasao', label: 'Evasão' },
  { value: 'observacao', label: 'Observação' },
]

/** Origem da internação (Admission.AdmissionSource) — para o desfecho internação. */
export const ADMISSION_SOURCE_OPTIONS: ChoiceOption[] = [
  { value: 'emergencia', label: 'Emergência' },
  { value: 'ambulatorio', label: 'Ambulatório' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'centro_cirurgico', label: 'Centro cirúrgico' },
  { value: 'outro', label: 'Outro' },
]

// ─── Action lifecycle helpers (which actions apply to a status) ──────────────

/** Classify / re-triagem is possible while aguardando ou já classificado. */
export function canClassifyStatus(status: string): boolean {
  return status === 'aguardando_classificacao' || status === 'classificado'
}

/** Chamar/iniciar atendimento only from `classificado` (backend 409 otherwise). */
export function canStartAttendanceStatus(status: string): boolean {
  return status === 'classificado'
}

/** Desfecho (encerramento) possible enquanto o boletim não estiver encerrado. */
export function canCloseStatus(status: string): boolean {
  return status !== 'encerrado'
}

// ─── Formatting helpers ──────────────────────────────────────────────────────

/** Tempo de espera em minutos → texto coarse pt-BR (ex.: "5min", "1h 20min"). */
export function formatWaited(minutes: number | null | undefined): string {
  if (minutes == null || minutes < 0) return '—'
  if (minutes < 60) return `${minutes}min`
  const h = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${h}h` : `${h}h ${rest}min`
}

/** HH:mm de um ISO datetime em hora local pt-BR (else '—'). */
export function formatArrival(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

/** Label de um profissional para os pickers (user_name → registro → id). */
export function professionalLabel(p: ProfessionalOption): string {
  return p.user_name || (p.council_number ? `Registro ${p.council_number}` : p.id)
}
