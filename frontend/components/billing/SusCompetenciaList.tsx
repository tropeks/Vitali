'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarPlus, RefreshCw } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import {
  isValidCompetencia,
  normalizeList,
  susStatusMeta,
  type FacilityOption,
  type ListResponse,
  type SusCompetencia,
} from './sus-types'

interface Props {
  /** `sus.write` — gates the "criar competência" form. */
  canWrite: boolean
  /** Selecting a competência opens its detail. */
  onSelect: (competenciaId: number) => void
}

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Todas as situações' },
  { value: 'aberta', label: 'Aberta' },
  { value: 'fechada', label: 'Fechada' },
  { value: 'exportada', label: 'Exportada' },
]

/**
 * Competências SUS — lista filtrável (establishment/status) + criação de nova
 * janela mensal de faturamento. Reads `sus.read`; a criação exige `sus.write`.
 * Selecionar uma linha abre o detalhe (via `onSelect`).
 */
export default function SusCompetenciaList({ canWrite, onSelect }: Props) {
  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [rows, setRows] = useState<SusCompetencia[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [establishmentFilter, setEstablishmentFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const [newEstablishment, setNewEstablishment] = useState('')
  const [newCompetencia, setNewCompetencia] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const facilityName = useMemo(() => {
    const map: Record<string, string> = {}
    for (const facility of facilities) map[facility.id] = facility.name
    return map
  }, [facilities])

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const params = new URLSearchParams()
      if (establishmentFilter) params.set('establishment', establishmentFilter)
      if (statusFilter) params.set('status', statusFilter)
      const query = params.toString()
      const data = await apiFetch<ListResponse<SusCompetencia> | SusCompetencia[]>(
        `/api/v1/billing/sus-competencias/${query ? `?${query}` : ''}`,
      )
      setRows(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [establishmentFilter, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    apiFetch<ListResponse<FacilityOption> | FacilityOption[]>('/api/v1/organization/facilities/')
      .then((data) => setFacilities(normalizeList(data)))
      .catch(() => setFacilities([]))
  }, [])

  const canSubmit = newEstablishment !== '' && isValidCompetencia(newCompetencia)

  const submitCreate = async () => {
    if (!canSubmit) return
    setCreating(true)
    setCreateError('')
    try {
      const created = await apiFetch<SusCompetencia>('/api/v1/billing/sus-competencias/', {
        method: 'POST',
        body: JSON.stringify({
          establishment: newEstablishment,
          competencia: newCompetencia.trim(),
        }),
      })
      setNewCompetencia('')
      await load()
      if (created?.id != null) onSelect(created.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setCreateError('Competência já existe para este estabelecimento ou dados inválidos.')
      } else {
        setCreateError('Não foi possível criar a competência. Tente novamente.')
      }
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-5">
      {canWrite && (
        <section className="rounded-lg border border-slate-200 bg-neu-panel p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-neu-ink">
            <CalendarPlus size={16} className="text-blue-600" />
            Nova competência
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Estabelecimento (CNES)
              <select
                aria-label="Estabelecimento da nova competência"
                value={newEstablishment}
                onChange={(event) => setNewEstablishment(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                <option value="">Selecione…</option>
                {facilities.map((facility) => (
                  <option key={facility.id} value={facility.id}>
                    {facility.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Competência (AAAA-MM)
              <input
                aria-label="Competência (AAAA-MM)"
                value={newCompetencia}
                onChange={(event) => setNewCompetencia(event.target.value)}
                placeholder="2026-07"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <div className="flex items-end">
              <button
                type="button"
                onClick={submitCreate}
                disabled={!canSubmit || creating}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {creating ? 'Criando…' : 'Criar competência'}
              </button>
            </div>
          </div>
          {createError && <p className="mt-2 text-xs font-semibold text-red-700">{createError}</p>}
        </section>
      )}

      <section className="rounded-lg border border-slate-200 bg-neu-panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neu-ink">Competências</h2>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Filtrar por estabelecimento"
              value={establishmentFilter}
              onChange={(event) => setEstablishmentFilter(event.target.value)}
              className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
            >
              <option value="">Todos os estabelecimentos</option>
              {facilities.map((facility) => (
                <option key={facility.id} value={facility.id}>
                  {facility.name}
                </option>
              ))}
            </select>
            <select
              aria-label="Filtrar por situação"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
            >
              {STATUS_FILTERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <div className="p-4">
            <SectionState
              title="Carregando competências…"
              detail="Buscando as janelas de faturamento SUS."
            />
          </div>
        ) : error ? (
          <div className="p-4">
            <SectionState
              title="Erro ao carregar competências"
              detail="Não foi possível carregar as competências SUS. Tente novamente."
              tone="critical"
              action={
                <button
                  onClick={load}
                  className="inline-flex items-center gap-2 text-xs font-semibold text-red-700 hover:underline"
                >
                  <RefreshCw size={13} />
                  Tentar novamente
                </button>
              }
            />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <SectionState
              title="Nenhuma competência"
              detail="Não há competências SUS para os filtros selecionados."
            />
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100">
              <tr>
                {['Competência', 'Estabelecimento', 'Situação'].map((header) => (
                  <th
                    key={header}
                    className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => onSelect(row.id)}
                  className="cursor-pointer transition-colors hover:bg-blue-50"
                >
                  <td className="px-4 py-3 font-mono font-medium text-neu-ink">{row.competencia}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">
                    {facilityName[row.establishment] ?? row.establishment}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge meta={susStatusMeta(row.status)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
