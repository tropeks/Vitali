'use client'

/**
 * A8: Read-only browser for one shared, platform-governed terminology catalog
 * (CBO/CNES/LOINC/UCUM). Consumes GET /api/v1/platform/terminology/<system>/,
 * which is paginated as { results, count } (falls back to a plain array).
 *
 * Item shape varies per catalog (code/description are the common denominator
 * across CBO/CNES/LOINC/UCUM rows), so field lookups fall back defensively
 * across the field names each governed source tends to use.
 */
import { useCallback, useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'

interface CatalogBrowserProps {
  system: string
  label: string
  onClose: () => void
}

const PAGE_SIZE = 20

function itemCode(item: any): string {
  return item?.code ?? item?.id ?? '—'
}

function itemDescription(item: any): string {
  return (
    item?.description ??
    item?.long_common_name ??
    item?.display_name ??
    item?.display ??
    item?.name ??
    '—'
  )
}

export default function CatalogBrowser({ system, label, onClose }: CatalogBrowserProps) {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [items, setItems] = useState<any[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (search) params.set('search', search)
      params.set('page', String(page))
      const data = await apiFetch<any>(`/api/v1/platform/terminology/${system}/?${params.toString()}`)
      const results = Array.isArray(data) ? data : (data?.results ?? [])
      setItems(results)
      setCount(Array.isArray(data) ? results.length : (data?.count ?? results.length))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }, [system, search, page])

  useEffect(() => {
    load()
  }, [load])

  const totalPages = Math.max(1, Math.ceil(count / PAGE_SIZE))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-900">Catálogo {label}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-600 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-4 py-3 border-b border-slate-100">
          <input
            type="text"
            placeholder="Buscar por código ou descrição..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {error ? (
            <SectionState title="Erro ao carregar catálogo" detail={error} tone="critical" />
          ) : loading ? (
            <SectionState title="Carregando..." detail="Buscando itens do catálogo." tone="neutral" />
          ) : items.length === 0 ? (
            <SectionState
              title="Nenhum item encontrado"
              detail="Nenhum item corresponde à busca."
              tone="neutral"
            />
          ) : (
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-medium">Código</th>
                  <th className="px-3 py-2 font-medium">Descrição</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => (
                  <tr key={item?.id ?? item?.code ?? idx} className="border-t border-slate-50">
                    <td className="px-3 py-2 font-mono text-slate-700">{itemCode(item)}</td>
                    <td className="px-3 py-2 text-slate-600">{itemDescription(item)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 text-sm">
          <span className="text-slate-500">
            {count} item{count !== 1 ? 's' : ''}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="px-2.5 py-1.5 text-xs font-medium border border-slate-200 rounded-lg disabled:opacity-40"
            >
              Anterior
            </button>
            <span className="text-xs text-slate-500">
              Página {page} de {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="px-2.5 py-1.5 text-xs font-medium border border-slate-200 rounded-lg disabled:opacity-40"
            >
              Próxima
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
