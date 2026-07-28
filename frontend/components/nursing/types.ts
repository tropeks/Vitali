/**
 * Shared shapes/helpers for the SAE nursing-process components (N4).
 */

export interface SaeListResponse<T> {
  results?: T[]
  count?: number
}

/** A NANDA/NIC/NOC terminology autocomplete result. The picker exposes only a
 * `code`/`display` pair — there is no catalog PK — so writes carry `*_code`. */
export interface TerminologyOption {
  system?: string
  code: string
  display: string
  active?: boolean
}

export type NandaOption = TerminologyOption
export type NicOption = TerminologyOption
export type NocOption = TerminologyOption

export function normalizeSaeList<T>(
  payload: SaeListResponse<T> | T[] | null | undefined
): T[] {
  if (!payload) return []
  if (Array.isArray(payload)) return payload
  return payload.results ?? []
}

export function formatSaeDateTime(value?: string | null): string | null {
  if (!value) return null
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
