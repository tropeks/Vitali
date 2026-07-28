'use client'

import { useCallback, useEffect, useState } from 'react'
import { PackagePlus, PlusCircle, RefreshCw, Trash2 } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  LATERALITY_OPTIONS,
  MATERIAL_KIND_OPTIONS,
  labelOf,
  normalizeList,
  type ListResponse,
  type SurgicalMaterial,
} from './surgery-case-types'

interface Props {
  caseId: string
  /** `surgery.manage` — gates the add form, consume and remove controls. */
  canManage: boolean
}

interface AddForm {
  kind: string
  description: string
  quantity_planned: string
  laterality: string
  lot: string
  serial: string
  manufacturer: string
}

const EMPTY_FORM: AddForm = {
  kind: MATERIAL_KIND_OPTIONS[0].value,
  description: '',
  quantity_planned: '1',
  laterality: '',
  lot: '',
  serial: '',
  manufacturer: '',
}

/**
 * Materiais / OPME (C6) — planned vs consumed materials of a single case.
 * Reading is visible with `surgery.read` (`GET /surgical-materials/?case=`);
 * adding (`POST /surgical-materials/`), registering consumption
 * (`POST /surgical-materials/{id}/consume/`) and removing
 * (`DELETE /surgical-materials/{id}/`) are gated by `surgery.manage`. An
 * invalid consume quantity → 400, surfaced as a friendly inline message.
 */
export default function SurgeryMaterialsPanel({ caseId, canManage }: Props) {
  const [materials, setMaterials] = useState<SurgicalMaterial[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [form, setForm] = useState<AddForm>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [addError, setAddError] = useState('')

  const [consumeQty, setConsumeQty] = useState<Record<string, string>>({})
  const [rowError, setRowError] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse<SurgicalMaterial> | SurgicalMaterial[]>(
        `/api/v1/surgical-materials/?case=${caseId}`,
      )
      setMaterials(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => {
    load()
  }, [load])

  const isOpme = form.kind === 'opme'

  const add = async () => {
    if (!form.description.trim()) {
      setAddError('Informe a descrição do material.')
      return
    }
    const planned = Number(form.quantity_planned)
    if (!Number.isInteger(planned) || planned < 1) {
      setAddError('Quantidade planejada inválida.')
      return
    }
    setSaving(true)
    setAddError('')
    try {
      const body: Record<string, unknown> = {
        case: caseId,
        kind: form.kind,
        description: form.description.trim(),
        quantity_planned: planned,
      }
      if (form.laterality) body.laterality = form.laterality
      if (form.lot.trim()) body.lot = form.lot.trim()
      if (form.serial.trim()) body.serial = form.serial.trim()
      if (form.manufacturer.trim()) body.manufacturer = form.manufacturer.trim()
      await apiFetch('/api/v1/surgical-materials/', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      setForm(EMPTY_FORM)
      await load()
    } catch {
      setAddError('Não foi possível adicionar o material. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  const consume = async (material: SurgicalMaterial) => {
    const raw = consumeQty[material.id] ?? ''
    const quantity = Number(raw)
    setRowError((prev) => ({ ...prev, [material.id]: '' }))
    if (!Number.isInteger(quantity) || quantity < 1) {
      setRowError((prev) => ({ ...prev, [material.id]: 'Quantidade inválida.' }))
      return
    }
    setBusyId(material.id)
    try {
      await apiFetch(`/api/v1/surgical-materials/${material.id}/consume/`, {
        method: 'POST',
        body: JSON.stringify({ quantity }),
      })
      setConsumeQty((prev) => ({ ...prev, [material.id]: '' }))
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setRowError((prev) => ({ ...prev, [material.id]: 'Quantidade inválida.' }))
      } else {
        setRowError((prev) => ({
          ...prev,
          [material.id]: 'Não foi possível registrar o consumo. Tente novamente.',
        }))
      }
    } finally {
      setBusyId('')
    }
  }

  const remove = async (material: SurgicalMaterial) => {
    const label = material.description || labelOf(MATERIAL_KIND_OPTIONS, material.kind)
    if (!confirm(`Remover ${label} do caso?`)) return
    setBusyId(material.id)
    try {
      await apiFetch(`/api/v1/surgical-materials/${material.id}/`, { method: 'DELETE' })
      await load()
    } catch {
      setRowError((prev) => ({
        ...prev,
        [material.id]: 'Não foi possível remover o material. Tente novamente.',
      }))
    } finally {
      setBusyId('')
    }
  }

  if (loading) {
    return (
      <SectionState
        title="Carregando materiais / OPME..."
        detail="Buscando materiais planejados e consumidos do caso."
      />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar materiais / OPME"
        detail="Não foi possível carregar os materiais do caso. Tente novamente."
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
    )
  }

  return (
    <div className="space-y-3">
      {materials.length === 0 ? (
        <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
          Nenhum material / OPME registrado neste caso.
        </p>
      ) : (
        <ul className="space-y-2" aria-label="Materiais / OPME">
          {materials.map((material) => {
            const label = material.description || labelOf(MATERIAL_KIND_OPTIONS, material.kind)
            const opmeDetails = [
              material.lot ? `Lote ${material.lot}` : '',
              material.serial ? `Série ${material.serial}` : '',
              material.manufacturer || '',
              material.laterality ? labelOf(LATERALITY_OPTIONS, material.laterality) : '',
            ].filter(Boolean)
            return (
              <li
                key={material.id}
                className="rounded-lg border border-slate-200 bg-white px-4 py-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">{label}</p>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                        {labelOf(MATERIAL_KIND_OPTIONS, material.kind)}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Consumido{' '}
                      <span className="font-semibold text-slate-700">
                        {material.quantity_consumed} / {material.quantity_planned}
                      </span>{' '}
                      (consumido / planejado)
                    </p>
                    {opmeDetails.length > 0 && (
                      <p className="mt-0.5 text-xs text-slate-500">{opmeDetails.join(' · ')}</p>
                    )}
                  </div>
                  {canManage && (
                    <button
                      type="button"
                      onClick={() => remove(material)}
                      disabled={busyId === material.id}
                      aria-label={`Remover ${label}`}
                      className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-red-600 hover:underline disabled:opacity-60"
                    >
                      <Trash2 size={14} />
                      Remover
                    </button>
                  )}
                </div>

                {canManage && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                    <input
                      type="number"
                      min={1}
                      aria-label={`Consumo de ${label}`}
                      value={consumeQty[material.id] ?? ''}
                      onChange={(e) =>
                        setConsumeQty((prev) => ({ ...prev, [material.id]: e.target.value }))
                      }
                      placeholder="Qtd."
                      className="w-20 rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => consume(material)}
                      disabled={busyId === material.id}
                      className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-60"
                    >
                      <PlusCircle size={14} />
                      Registrar consumo
                    </button>
                    {rowError[material.id] && (
                      <span className="text-xs font-semibold text-red-700">
                        {rowError[material.id]}
                      </span>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {canManage && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-2">
            <PackagePlus size={15} className="text-blue-600" />
            <span className="text-sm font-semibold text-slate-900">Adicionar material / OPME</span>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="block text-xs font-semibold text-slate-600">
              Tipo
              <select
                aria-label="Tipo"
                value={form.kind}
                onChange={(e) => setForm((prev) => ({ ...prev, kind: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                {MATERIAL_KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-semibold text-slate-600">
              Quantidade planejada
              <input
                type="number"
                min={1}
                aria-label="Quantidade planejada"
                value={form.quantity_planned}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, quantity_planned: e.target.value }))
                }
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs font-semibold text-slate-600 sm:col-span-2">
              Descrição
              <input
                type="text"
                aria-label="Descrição"
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                placeholder="Ex.: Placa de titânio 3.5mm"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            {isOpme && (
              <>
                <label className="block text-xs font-semibold text-slate-600">
                  Lote (OPME)
                  <input
                    type="text"
                    aria-label="Lote (OPME)"
                    value={form.lot}
                    onChange={(e) => setForm((prev) => ({ ...prev, lot: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  />
                </label>
                <label className="block text-xs font-semibold text-slate-600">
                  Número de série (OPME)
                  <input
                    type="text"
                    aria-label="Número de série (OPME)"
                    value={form.serial}
                    onChange={(e) => setForm((prev) => ({ ...prev, serial: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  />
                </label>
                <label className="block text-xs font-semibold text-slate-600">
                  Fabricante
                  <input
                    type="text"
                    aria-label="Fabricante"
                    value={form.manufacturer}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, manufacturer: e.target.value }))
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  />
                </label>
                <label className="block text-xs font-semibold text-slate-600">
                  Lateralidade
                  <select
                    aria-label="Lateralidade"
                    value={form.laterality}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, laterality: e.target.value }))
                    }
                    className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  >
                    {LATERALITY_OPTIONS.map((option) => (
                      <option key={option.value || 'na'} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>
          {addError && <p className="mt-2 text-xs font-semibold text-red-700">{addError}</p>}
          <button
            type="button"
            onClick={add}
            disabled={saving}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            <PlusCircle size={15} />
            {saving ? 'Adicionando...' : 'Adicionar material'}
          </button>
        </div>
      )}
    </div>
  )
}
