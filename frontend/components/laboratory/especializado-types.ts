/**
 * Lab especializado — tipos + mapas de badge para microbiologia estruturada
 * (MB1) e anatomia patológica (AP1). Espelham EXATAMENTE os serializers do
 * backend (apps/emr/serializers_microbiology.py e serializers_pathology.py):
 * leitura aninhada result→organisms→antibiogram e report→specimens. Ids são
 * strings (UUID) na wire.
 */

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

// ─── Microbiologia (GET /api/v1/microbiology-results/?patient=) ───────────────

export interface AntibiogramEntry {
  id: string
  organism: string
  antibiotic: string
  method?: string
  mic_value?: string
  /** S / I / R / SDD (AntibiogramEntry.Interpretation). */
  interpretation: string
  notes?: string
  created_at?: string
}

export interface IsolatedOrganism {
  id: string
  result: string
  organism_name: string
  colony_count?: string
  is_significant: boolean
  notes?: string
  antibiogram: AntibiogramEntry[]
  created_at?: string
}

export interface MicrobiologyResult {
  id: string
  order_item: string
  /** positiva / negativa / contaminada / pendente. */
  culture_result: string
  specimen?: string
  collected_at?: string | null
  gram_stain?: string
  notes?: string
  organisms: IsolatedOrganism[]
  created_at?: string
  updated_at?: string
}

// ─── Anatomia patológica (GET /api/v1/pathology-reports/?patient=) ────────────

export interface PathologySpecimen {
  id: string
  report: string
  label: string
  description?: string
  site?: string
  blocks_count: number
  notes?: string
  created_at?: string
}

export interface PathologyReport {
  id: string
  order_item: string
  report_number?: string
  clinical_history?: string
  specimen_description?: string
  macroscopy?: string
  microscopy?: string
  immunohistochemistry?: string
  diagnosis?: string
  cid_o_topography?: string
  cid_o_morphology?: string
  /** Código CID-O efetivo (property do backend: FK governada reconciliada ou texto). */
  cid_o_topography_code?: string
  cid_o_morphology_code?: string
  cid_o_topography_unmatched?: boolean
  cid_o_morphology_unmatched?: boolean
  surgical_case?: string | null
  pathologist?: string | null
  /** pendente / preliminar / final. */
  status: string
  reported_at?: string | null
  specimens: PathologySpecimen[]
  created_at?: string
  updated_at?: string
}

// ─── badge maps ───────────────────────────────────────────────────────────────

interface BadgeMeta {
  label: string
  badgeClass: string
}

const NEUTRAL_BADGE = 'border-slate-200 bg-slate-50 text-slate-600'

export const CULTURE_RESULT_META: Record<string, BadgeMeta> = {
  positiva: { label: 'Positiva', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
  negativa: { label: 'Negativa', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
  contaminada: { label: 'Contaminada', badgeClass: 'border-amber-200 bg-amber-50 text-amber-700' },
  pendente: { label: 'Pendente', badgeClass: NEUTRAL_BADGE },
}

export function cultureResultMeta(status: string): BadgeMeta {
  return CULTURE_RESULT_META[status] ?? { label: status, badgeClass: NEUTRAL_BADGE }
}

/** Antibiograma: S verde, I âmbar, R vermelho, SDD azul (padrão CLSI). */
export const ANTIBIOGRAM_META: Record<string, BadgeMeta> = {
  S: { label: 'S', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
  I: { label: 'I', badgeClass: 'border-amber-200 bg-amber-50 text-amber-700' },
  R: { label: 'R', badgeClass: 'border-red-200 bg-red-50 text-red-700' },
  SDD: { label: 'SDD', badgeClass: 'border-blue-200 bg-blue-50 text-blue-700' },
}

export function antibiogramMeta(interpretation: string): BadgeMeta {
  return ANTIBIOGRAM_META[interpretation] ?? { label: interpretation, badgeClass: NEUTRAL_BADGE }
}

export const PATHOLOGY_STATUS_META: Record<string, BadgeMeta> = {
  pendente: { label: 'Pendente', badgeClass: NEUTRAL_BADGE },
  preliminar: { label: 'Preliminar', badgeClass: 'border-amber-200 bg-amber-50 text-amber-700' },
  final: { label: 'Final', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
}

export function pathologyStatusMeta(status: string): BadgeMeta {
  return PATHOLOGY_STATUS_META[status] ?? { label: status, badgeClass: NEUTRAL_BADGE }
}

// ─── option lists (forms) ─────────────────────────────────────────────────────

export const CULTURE_RESULT_OPTIONS = [
  { value: 'positiva', label: 'Positiva' },
  { value: 'negativa', label: 'Negativa' },
  { value: 'contaminada', label: 'Contaminada' },
  { value: 'pendente', label: 'Pendente' },
]

export const ANTIBIOGRAM_OPTIONS = [
  { value: 'S', label: 'S — Sensível' },
  { value: 'I', label: 'I — Intermediário' },
  { value: 'R', label: 'R — Resistente' },
  { value: 'SDD', label: 'SDD — Sensível dose-dependente' },
]

export const PATHOLOGY_STATUS_OPTIONS = [
  { value: 'pendente', label: 'Pendente' },
  { value: 'preliminar', label: 'Preliminar' },
  { value: 'final', label: 'Final' },
]

/** ISO datetime → short pt-BR date (e.g. "05/07/2026"), or "—". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(d)
}
