'use client'

/**
 * A8: Platform admin panel — governed terminology catalogs.
 *
 * Shows an import-status dashboard for the SHARED, platform-governed
 * terminology catalogs (CBO, CNES, LOINC, UCUM): row count and last import
 * (date/status/version) per catalog, a read-only browser ("Ver"), and a CSV
 * import action ("Importar CSV") per catalog. Platform-admin-only (superuser),
 * enforced by the backend (`IsPlatformAdmin`) — this page carries no separate
 * client-side gate, mirroring platform/tenants.
 *
 * Consumes:
 *   GET  /api/v1/platform/terminology/import-status/  (this page)
 *   GET  /api/v1/platform/terminology/<system>/        (CatalogBrowser)
 *   POST /api/v1/platform/terminology/<system>/import/ (ImportModal)
 */

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { CATALOGS } from '@/components/terminology/catalogs'
import CatalogImportRow, { type ImportStatusRow } from '@/components/terminology/CatalogImportRow'
import CatalogBrowser from '@/components/terminology/CatalogBrowser'
import ImportModal from '@/components/terminology/ImportModal'

export default function PlatformTerminologyPage() {
  const [rows, setRows] = useState<ImportStatusRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [browsingSystem, setBrowsingSystem] = useState<string | null>(null)
  const [importingSystem, setImportingSystem] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<ImportStatusRow[]>('/api/v1/platform/terminology/import-status/')
      setRows(Array.isArray(data) ? data : [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const statusBySystem = new Map(rows.map((r) => [r.system, r]))

  const browsingCatalog = CATALOGS.find((c) => c.system === browsingSystem)
  const importingCatalog = CATALOGS.find((c) => c.system === importingSystem)

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Terminologias governadas</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Catálogos compartilhados (CBO, CNES, LOINC, UCUM) — status de importação e navegação.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchStatus}
          className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50"
        >
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          Atualizar
        </button>
      </div>

      <div className="mt-5">
        {error ? (
          <SectionState title="Erro ao carregar status de importação" detail={error} tone="critical" />
        ) : loading && rows.length === 0 ? (
          <SectionState title="Carregando..." detail="Buscando status dos catálogos." tone="neutral" />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 font-medium">Catálogo</th>
                  <th className="px-4 py-3 font-medium">Registros</th>
                  <th className="px-4 py-3 font-medium">Última importação</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Versão</th>
                  <th className="px-4 py-3 font-medium text-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {CATALOGS.map((catalog) => (
                  <CatalogImportRow
                    key={catalog.system}
                    system={catalog.system}
                    label={catalog.label}
                    status={statusBySystem.get(catalog.system)}
                    onView={() => setBrowsingSystem(catalog.system)}
                    onImport={() => setImportingSystem(catalog.system)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {browsingCatalog && (
        <CatalogBrowser
          system={browsingCatalog.system}
          label={browsingCatalog.label}
          onClose={() => setBrowsingSystem(null)}
        />
      )}

      {importingCatalog && (
        <ImportModal
          system={importingCatalog.system}
          label={importingCatalog.label}
          onClose={() => setImportingSystem(null)}
          onImported={() => {
            setImportingSystem(null)
            fetchStatus()
          }}
        />
      )}
    </PageShell>
  )
}
