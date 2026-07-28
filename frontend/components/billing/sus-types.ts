/**
 * Faturamento SUS (S4) — shared types, option shapes, enum→label maps and small
 * helpers for the BPA/APAC surface (`app/(dashboard)/billing/sus`).
 *
 * Shapes mirror `backend/apps/billing/serializers_sus.py` EXACTLY:
 *   - `SusCompetencia`, `BpaConsolidado`, `BpaIndividualizado`, `ApacAutorizacao`
 *     ids are INTEGER pks (as DRF emits them for these models). `sigtap` / `cbo`
 *     / `procedimento_principal` are the cross-schema catalog INTEGER pks;
 *     `establishment` / `patient` / `professional*` are UUID strings.
 *   - money fields (`valor`, `total_valor`) arrive as decimal STRINGS.
 *
 * API-shape caveat (BPA-C `cbo`): the only `sus`-gated CBO search endpoint,
 * `/api/v1/terminology/cbo/?q=`, returns `{code, display}` but NOT the CBOCode
 * INTEGER pk the serializer's `cbo` PrimaryKeyRelatedField requires. Until the
 * backend exposes an `id` there (or a `/cbo/?q=` list mirroring `/sigtap/`), the
 * CBO option's `id` may be absent and the POST will 400 in production. Tracked as
 * a backend follow-up — see the S4 report.
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

export type SusStatus = 'aberta' | 'fechada' | 'exportada'

export interface SusCompetencia {
  id: number
  establishment: string
  competencia: string
  status: SusStatus | string
  exportada_at?: string | null
  created_by?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export interface BpaConsolidadoLine {
  id: number
  competencia: number
  sigtap: number
  cbo: number
  idade: number
  quantidade: number
  valor: string
  created_at?: string | null
}

export interface BpaIndividualizadoLine {
  id: number
  competencia: number
  sigtap: number
  cbo?: number | null
  patient: string
  cns?: string
  cid?: string
  professional?: string | null
  quantidade: number
  valor: string
  encounter_procedure?: string | null
  created_at?: string | null
}

export interface ApacAutorizacaoLine {
  id: number
  competencia: number
  numero_apac: string
  validade_inicio: string
  validade_fim: string
  procedimento_principal: number
  cid_principal?: string
  patient: string
  cns?: string
  professional_solicitante?: string | null
  professional_executante?: string | null
  valor: string
  created_by?: number | null
  created_at?: string | null
}

/** Response of `POST sus-competencias/{id}/gerar-producao/`. */
export interface GerarProducaoResult {
  bpa_i_count: number
  total_valor: string
}

/** Response of `POST sus-competencias/{id}/exportar/`. */
export interface ExportarResult {
  remessa_bpa: string
  remessa_apac: string
  filename_bpa: string
  filename_apac: string
}

// ─── Picker option shapes ────────────────────────────────────────────────────

/** Facility (establishment/CNES) option — `/organization/facilities/`. */
export interface FacilityOption {
  id: string
  name: string
}

/** SIGTAP procedure option — `/sigtap/?q=` (INTEGER pk in `id`). */
export interface SigtapOption {
  id: number
  code: string
  display: string
  valor_total?: string
}

/**
 * CBO occupation option — `/terminology/cbo/?q=`. `id` is the CBOCode pk the
 * BPA-C serializer needs, but the terminology autocomplete does not currently
 * emit it (see module caveat) — hence optional.
 */
export interface CboOption {
  id?: number
  code: string
  display: string
}

/** Patient option — `/patients/?search=`. */
export interface PatientOption {
  id: string
  full_name: string
}

/** Professional option — `/professionals/?search=`. */
export interface ProfessionalOption {
  id: string
  user_name?: string | null
  council_number?: string | null
}

// ─── enum → label maps ───────────────────────────────────────────────────────

export const SUS_STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  aberta: { label: 'Aberta', badgeClass: 'border-blue-200 bg-blue-50 text-blue-700' },
  fechada: { label: 'Fechada', badgeClass: 'border-amber-200 bg-amber-50 text-amber-700' },
  exportada: { label: 'Exportada', badgeClass: 'border-green-200 bg-green-50 text-green-700' },
}

export function susStatusMeta(status: string): { label: string; badgeClass: string } {
  return (
    SUS_STATUS_META[status] ?? {
      label: status,
      badgeClass: 'border-slate-200 bg-slate-50 text-slate-600',
    }
  )
}

// ─── helpers ─────────────────────────────────────────────────────────────────

/** A competência string is valid iff it matches `AAAA-MM`. */
export function isValidCompetencia(value: string): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value.trim())
}

/** pt-BR BRL formatter (amounts arrive as decimal strings). */
export function formatBRL(value: string | number | null | undefined): string {
  return Number(value ?? 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

/** Sum a list of decimal-string `valor` fields into a Number. */
export function sumValores(rows: Array<{ valor?: string | number | null }>): number {
  return rows.reduce((acc, row) => acc + Number(row.valor ?? 0), 0)
}

/**
 * Client-side text download: builds a `text/plain` Blob and clicks a transient
 * `<a download>`. Used to save the exported DATASUS remessa `.txt` files with no
 * external libraries. Guards SSR (no `document`).
 */
export function downloadTextFile(filename: string, content: string): void {
  if (typeof document === 'undefined') return
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
