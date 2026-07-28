'use client'

import { StatusBadge } from '@/components/shared'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ImportStatusRow {
  system: string
  row_count: number
  last_import_at: string | null
  last_import_status: string | null
  last_import_version: string | null
}

interface CatalogImportRowProps {
  system: string
  label: string
  status?: ImportStatusRow
  onView: () => void
  onImport: () => void
}

// ─── Status → badge mapping (import run status is admin-only, mapped locally) ─

const STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  success: { label: 'Sucesso', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  completed: { label: 'Sucesso', badgeClass: 'bg-green-100 text-green-800 border-green-200' },
  failed: { label: 'Falhou', badgeClass: 'bg-red-100 text-red-700 border-red-200' },
  error: { label: 'Falhou', badgeClass: 'bg-red-100 text-red-700 border-red-200' },
  running: { label: 'Em execução', badgeClass: 'bg-blue-100 text-blue-800 border-blue-200' },
}

const NEVER_IMPORTED_META = { label: 'Nunca importado', badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' }

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('pt-BR')
}

function formatCount(value: number | undefined): string {
  return (value ?? 0).toLocaleString('pt-BR')
}

// ─── Row ──────────────────────────────────────────────────────────────────────

export default function CatalogImportRow({ system, label, status, onView, onImport }: CatalogImportRowProps) {
  const meta = status?.last_import_status
    ? (STATUS_META[status.last_import_status] ?? { label: status.last_import_status, badgeClass: 'bg-slate-100 text-slate-600 border-slate-200' })
    : NEVER_IMPORTED_META

  return (
    <tr data-testid={`catalog-row-${system}`} className="border-b border-slate-50 last:border-0">
      <td className="px-4 py-3 font-medium text-slate-900">{label}</td>
      <td className="px-4 py-3 text-slate-600">{formatCount(status?.row_count)}</td>
      <td className="px-4 py-3 text-slate-600">{formatDate(status?.last_import_at)}</td>
      <td className="px-4 py-3">
        <StatusBadge meta={meta} />
      </td>
      <td className="px-4 py-3 text-slate-600">{status?.last_import_version ?? '—'}</td>
      <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
        <button
          type="button"
          onClick={onView}
          className="inline-flex items-center px-2.5 py-1.5 text-xs font-medium text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-50"
        >
          Ver
        </button>
        <button
          type="button"
          onClick={onImport}
          className="inline-flex items-center px-2.5 py-1.5 text-xs font-medium text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-50"
        >
          Importar CSV
        </button>
      </td>
    </tr>
  )
}
