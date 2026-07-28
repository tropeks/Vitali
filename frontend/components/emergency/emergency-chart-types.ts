/**
 * PS/Emergência (E5) — shared types and enum→label maps for the emergency
 * surface (Emergência tab on the patient chart).
 *
 * Shapes mirror `backend/apps/emr/serializers_emergency.py` and
 * `backend/apps/core/serializers_manchester.py` EXACTLY. The boletim serializer
 * returns *pk ids* for `patient` / `encounter` / `admission` and embeds the
 * read-only `current_classification` (latest triagem). All ids are strings.
 * `acuity_level` / `target_minutes` are the STABLE copies taken from the
 * Manchester catalog at classify time.
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

/** Append-only Manchester risk classification (triagem) — read-only surface. */
export interface RiskClassification {
  id: string
  boletim: string
  flowchart: string
  flowchart_code?: string | null
  discriminator: string
  discriminator_code?: string | null
  acuity_level: string
  target_minutes: number
  vitals?: string | null
  classified_by?: string | null
  classified_at?: string | null
  notes?: string | null
  created_at?: string | null
}

/** Boletim de atendimento de emergência (BAE) — pk-based FKs, as emitted. */
export interface EmergencyEncounter {
  id: string
  patient: string
  encounter?: string | null
  arrival_at?: string | null
  mode_of_arrival: string
  chief_complaint?: string | null
  status: string
  disposition?: string | null
  admission?: string | null
  current_classification?: RiskClassification | null
  created_by?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** Manchester flowchart option (`/manchester-flowcharts/?q=`). */
export interface ManchesterFlowchartOption {
  id: string
  code: string
  display: string
  system?: string | null
  version?: string | null
  active?: boolean | null
}

/** Manchester discriminator option (`/manchester-discriminators/?flowchart=`). */
export interface ManchesterDiscriminatorOption {
  id: string
  flowchart: string
  code: string
  name: string
  description?: string | null
  acuity_level: string
  target_minutes: number
  is_general?: boolean | null
  active?: boolean | null
}

/** A free bed option for the internação disposition (`/beds/?status=livre`). */
export interface BedOption {
  id: string
  identifier: string
  status?: string | null
}

/** Professional option for the internação pickers (`/professionals/`). */
export interface ProfessionalOption {
  id: string
  user_name?: string | null
  council_number?: string | null
  specialty?: string | null
}

// ─── acuidade Manchester (mirror core.AcuityLevel + ACUITY_TARGET_MINUTES) ─────

export interface AcuityMeta {
  label: string
  badgeClass: string
  targetMinutes: number
}

export const ACUITY_META: Record<string, AcuityMeta> = {
  vermelho: {
    label: 'Vermelho (emergência)',
    badgeClass: 'border-red-300 bg-red-100 text-red-800',
    targetMinutes: 0,
  },
  laranja: {
    label: 'Laranja (muito urgente)',
    badgeClass: 'border-orange-300 bg-orange-100 text-orange-800',
    targetMinutes: 10,
  },
  amarelo: {
    label: 'Amarelo (urgente)',
    badgeClass: 'border-amber-300 bg-amber-100 text-amber-800',
    targetMinutes: 60,
  },
  verde: {
    label: 'Verde (pouco urgente)',
    badgeClass: 'border-green-300 bg-green-100 text-green-800',
    targetMinutes: 120,
  },
  azul: {
    label: 'Azul (não urgente)',
    badgeClass: 'border-blue-300 bg-blue-100 text-blue-800',
    targetMinutes: 240,
  },
}

/** Badge meta for an acuity level, with a safe fallback for unknown values. */
export function acuityMeta(level?: string | null): { label: string; badgeClass: string } {
  if (level && ACUITY_META[level]) {
    return { label: ACUITY_META[level].label, badgeClass: ACUITY_META[level].badgeClass }
  }
  return {
    label: level || 'Sem classificação',
    badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
  }
}

// ─── enum → label maps (mirror emergency_models TextChoices) ──────────────────

export const STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  aguardando_classificacao: {
    label: 'Aguardando classificação',
    badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
  },
  classificado: {
    label: 'Classificado',
    badgeClass: 'border-blue-200 bg-blue-50 text-blue-700',
  },
  em_atendimento: {
    label: 'Em atendimento',
    badgeClass: 'border-indigo-200 bg-indigo-50 text-indigo-700',
  },
  encerrado: {
    label: 'Encerrado',
    badgeClass: 'border-green-200 bg-green-50 text-green-700',
  },
}

export function statusMeta(status?: string | null): { label: string; badgeClass: string } {
  if (status && STATUS_META[status]) return STATUS_META[status]
  return {
    label: status || 'Indefinido',
    badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
  }
}

export const MODE_OF_ARRIVAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'ambulante', label: 'Ambulante' },
  { value: 'cadeira_rodas', label: 'Cadeira de rodas' },
  { value: 'maca', label: 'Maca' },
  { value: 'ambulancia', label: 'Ambulância' },
  { value: 'viatura_pm', label: 'Viatura (PM/SAMU)' },
  { value: 'outro', label: 'Outro' },
]

export const DISPOSITION_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'alta', label: 'Alta' },
  { value: 'internacao', label: 'Internação' },
  { value: 'transferencia_externa', label: 'Transferência externa' },
  { value: 'obito', label: 'Óbito' },
  { value: 'evasao', label: 'Evasão' },
  { value: 'observacao', label: 'Observação' },
]

export function labelOf(
  options: Array<{ value: string; label: string }>,
  value?: string | null,
): string {
  if (!value) return '—'
  return options.find((option) => option.value === value)?.label ?? value
}

/** pt-BR date/time formatter shared by the emergency components. */
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
