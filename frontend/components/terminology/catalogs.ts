/**
 * A8: Governança de terminologia (SaaS-owner).
 *
 * Fixed universe of shared, platform-governed terminology catalogs. These are
 * NOT tenant data — they're the shared reference tables (CBO, CNES, LOINC,
 * UCUM) that every clinic's records reconcile against. The catalog list is a
 * closed set (unlike tenants), so the dashboard always renders one row per
 * entry here regardless of what the backend's import-status endpoint returns.
 */
export interface CatalogDef {
  /** Path segment + backend `system` key, e.g. `/platform/terminology/cbo/`. */
  system: string
  label: string
}

export const CATALOGS: CatalogDef[] = [
  { system: 'cbo', label: 'CBO' },
  { system: 'cnes', label: 'CNES' },
  { system: 'loinc', label: 'LOINC' },
  { system: 'ucum', label: 'UCUM' },
]
