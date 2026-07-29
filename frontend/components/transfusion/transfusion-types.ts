/**
 * H6 — "Transfusão" prontuário tab: H6-specific shapes + enum→label maps.
 *
 * The requisição / crossmatch / component / bag / ABO-Rh / urgência / request-status
 * shapes are the SAME wire contract already modelled by the Banco de Sangue (H1–H5)
 * surface, so they are imported (never re-declared) from `bloodbank-types.ts`.
 * Only the bedside-specific pieces live here: the administração + reação DTOs, the
 * checagem dos "5 certos" verdict, the reaction/administration enum label maps, and
 * a couple of pt-BR formatters/helpers.
 *
 * Field names + enum values are copied verbatim from the backend serializers:
 *   backend/apps/emr/serializers_transfusion.py       (TransfusionRequest/CrossMatch)
 *   backend/apps/emr/serializers_transfusion_admin.py (Administration/Reaction)
 *   backend/apps/emr/transfusion_admin_models.py      (Status/Tipo/Gravidade choices)
 */

import {
  normalizeList,
  aboRhLabel,
  apiErrorDetail,
  formatDate,
  urgenciaMeta,
  requestStatusMeta,
  URGENCIA_OPTIONS,
  type ListResponse,
  type Meta,
  type BloodBagDTO,
  type BloodComponentDTO,
  type CrossMatchDTO,
  type RequestStatus,
  type TransfusionRequestDTO,
  type Urgencia,
} from '@/components/bloodbank/bloodbank-types'

// ─── re-exported shared shapes/helpers (single source of truth = bloodbank) ──
export { normalizeList, aboRhLabel, apiErrorDetail, formatDate, urgenciaMeta, requestStatusMeta, URGENCIA_OPTIONS }
export type {
  ListResponse,
  Meta,
  BloodBagDTO,
  BloodComponentDTO,
  CrossMatchDTO,
  RequestStatus,
  TransfusionRequestDTO,
  Urgencia,
}

/** Friendly alias used across the H6 components. */
export type TransfusionRequest = TransfusionRequestDTO
/** Hemocomponente catalog option for the requisição picker (H1 `blood-components`). */
export type BloodComponentOption = BloodComponentDTO

// ─── pt-BR date/time formatter (bloodbank has date-only) ─────────────────────

export function formatDateTime(value?: string | null): string {
  if (!value) return 'Não informado'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── requisição transfusional — POST body ────────────────────────────────────

/**
 * Body of `POST /api/v1/transfusion-requests/`. At least one order parent is
 * required by the backend; in the prontuário the natural one is the patient's
 * active `encounter`. The request does NOT carry a bag — the bolsa is picked at
 * the bedside checagem.
 */
export interface TransfusionRequestPayload {
  patient: string
  encounter?: string
  admission?: string
  component: number
  quantidade: number
  urgencia: Urgencia
  indicacao: string
  cid?: string
}

// ─── checagem beira-leito (5 certos da transfusão) ───────────────────────────

/**
 * Structured verdict of the transfusion "5 certos", returned inside the 422 body
 * of `POST /api/v1/transfusion-requests/<pk>/checar/` under `checagem`.
 */
export interface TransfusionCheck {
  paciente: boolean
  bolsa: boolean
  componente: boolean
  compatibilidade: boolean
  validade: boolean
  ok: boolean
  mismatches: string[]
}

/** 422 body: a "certo" failed and no override was supplied. */
export interface TransfusionCheckError {
  detail: string
  checagem: TransfusionCheck
}

/** Body of `POST /api/v1/transfusion-requests/<pk>/checar/`. */
export interface TransfusionCheckPayload {
  bag: string
  patient_barcode: string
  bag_barcode: string
  witness?: string
  override_reason?: string
}

/** The five "certos" in canonical order, matching the backend verifier. */
export const CERTOS_ORDER = [
  'paciente',
  'bolsa',
  'componente',
  'compatibilidade',
  'validade',
] as const

export type CertoKey = (typeof CERTOS_ORDER)[number]

/** pt-BR labels for each "certo". */
export const CERTO_LABELS: Record<CertoKey, string> = {
  paciente: 'Paciente',
  bolsa: 'Bolsa (DIN)',
  componente: 'Componente',
  compatibilidade: 'Compatibilidade ABO/Rh',
  validade: 'Validade',
}

// ─── administração transfusional (201 body / GET administrations) ────────────

export type AdminStatus = 'em_andamento' | 'concluida' | 'interrompida'

/**
 * An administração transfusional — the 201 body of `checar/` and the rows of
 * `GET /api/v1/transfusion-administrations/`. Faithful to
 * `TransfusionAdministrationSerializer` (there is NO `component_display` here; the
 * component is joined client-side from the parent requisição).
 */
export interface TransfusionAdministrationDTO {
  id: string
  request: string
  bag?: string | null
  bag_identifier?: string | null
  patient: string
  administered_by?: string | null
  witness?: string | null
  started_at?: string | null
  finished_at?: string | null
  volume_ml?: number | null
  status: AdminStatus
  patient_barcode_scanned?: string | null
  bag_barcode_scanned?: string | null
  checagem_verified?: boolean
  checagem_override_reason?: string | null
  created_at?: string | null
}

/** Friendly alias used across the H6 components. */
export type TransfusionAdministration = TransfusionAdministrationDTO

// ─── reação transfusional (hemovigilância) ───────────────────────────────────

export type ReactionTipo =
  | 'febril_nao_hemolitica'
  | 'alergica'
  | 'hemolitica_aguda'
  | 'trali'
  | 'taco'
  | 'contaminacao_bacteriana'
  | 'outra'

export type ReactionGravidade = 'leve' | 'moderada' | 'grave' | 'obito'

/** A reação transfusional row (`TransfusionReactionSerializer`). */
export interface TransfusionReactionDTO {
  id: string
  administration: string
  request?: string | null
  tipo: ReactionTipo
  gravidade: ReactionGravidade
  descricao: string
  conduta?: string | null
  notificado_hemovigilancia: boolean
  occurred_at?: string | null
  recorded_by?: string | null
  created_at?: string | null
}

export type TransfusionReaction = TransfusionReactionDTO

/** Body of `POST /api/v1/transfusion-administrations/<pk>/reacao/`. */
export interface TransfusionReactionPayload {
  tipo: ReactionTipo
  gravidade: ReactionGravidade
  descricao: string
  conduta?: string
  notificado_hemovigilancia: boolean
  occurred_at?: string
}

// ─── enum → option / badge maps (H6-specific) ────────────────────────────────

export const REACTION_TYPE_OPTIONS: Array<{ value: ReactionTipo; label: string }> = [
  { value: 'febril_nao_hemolitica', label: 'Febril não hemolítica' },
  { value: 'alergica', label: 'Alérgica' },
  { value: 'hemolitica_aguda', label: 'Hemolítica aguda' },
  { value: 'trali', label: 'TRALI (lesão pulmonar aguda)' },
  { value: 'taco', label: 'TACO (sobrecarga circulatória)' },
  { value: 'contaminacao_bacteriana', label: 'Contaminação bacteriana' },
  { value: 'outra', label: 'Outra' },
]

export const REACTION_SEVERITY_OPTIONS: Array<{ value: ReactionGravidade; label: string }> = [
  { value: 'leve', label: 'Leve' },
  { value: 'moderada', label: 'Moderada' },
  { value: 'grave', label: 'Grave' },
  { value: 'obito', label: 'Óbito' },
]

export const ADMIN_STATUS_META: Record<AdminStatus, Meta> = {
  em_andamento: { label: 'Em andamento', badgeClass: 'border-indigo-200 bg-indigo-50 text-indigo-700' },
  concluida: { label: 'Concluída', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
  interrompida: { label: 'Interrompida', badgeClass: 'border-red-300 bg-red-100 text-red-800' },
}

// ─── generic label/meta helpers with safe fallbacks ──────────────────────────

export function metaOf(map: Record<string, Meta>, value?: string | null): Meta {
  if (value && map[value]) return map[value]
  return { label: value || 'Indefinido', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' }
}

export function labelOf(
  options: Array<{ value: string; label: string }>,
  value?: string | null,
): string {
  if (!value) return '—'
  return options.find((option) => option.value === value)?.label ?? value
}

/**
 * Derive a single compatibilidade badge from a requisição's nested crossmatches.
 * Incompatível wins (any bag flagged incompatible), then Compatível (≥1 compatible
 * crossmatch), else null (no prova cruzada yet).
 */
export function crossmatchSummary(crossmatches?: CrossMatchDTO[] | null): Meta | null {
  if (!crossmatches || crossmatches.length === 0) return null
  if (crossmatches.some((cm) => cm.compativel === false)) {
    return { label: 'Incompatível', badgeClass: 'border-red-300 bg-red-100 text-red-800' }
  }
  if (crossmatches.some((cm) => cm.compativel === true)) {
    return { label: 'Compatível', badgeClass: 'border-green-200 bg-green-50 text-green-700' }
  }
  return { label: 'Prova cruzada pendente', badgeClass: 'border-slate-200 bg-slate-50 text-slate-600' }
}
