'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'

/**
 * RosterFormModal — create / edit a DutyRoster. Mirrors the `DutyRoster`
 * serializer (fields="__all__"): id, name, facility, start_date, end_date,
 * active, created_at, updated_at. Writable body = name/facility/start_date/
 * end_date/active (POST /api/v1/hr/duty-rosters/, PUT the detail endpoint).
 */

export interface DutyRoster {
  id: string
  name: string
  facility: string
  start_date: string
  end_date: string
  active: boolean
  created_at: string
  updated_at: string
}

interface FacilityOption {
  id: string
  name: string
}

type Listish<T> = T[] | { results: T[] }

function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : (data?.results ?? [])
}

export interface RosterFormModalProps {
  open: boolean
  roster?: DutyRoster | null
  onClose: () => void
  onSuccess?: (roster: DutyRoster) => void
}

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

function extractFieldErrors(body: any): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [key, val] of Object.entries(body)) {
    if (Array.isArray(val) && val.length > 0) errors[key] = String(val[0])
    else if (typeof val === 'string') errors[key] = val
  }
  return errors
}

export default function RosterFormModal({
  open,
  roster = null,
  onClose,
  onSuccess,
}: RosterFormModalProps) {
  const isEdit = roster != null

  const [name, setName] = useState('')
  const [facility, setFacility] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [active, setActive] = useState(true)

  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')

  // Seed the form whenever the modal opens (or the edited roster changes).
  useEffect(() => {
    if (!open) return
    setName(roster?.name ?? '')
    setFacility(roster?.facility ?? '')
    setStartDate(roster?.start_date ?? '')
    setEndDate(roster?.end_date ?? '')
    setActive(roster?.active ?? true)
    setFieldErrors({})
    setGlobalError('')
  }, [open, roster])

  // Load facilities for the select.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/')
      .then((data) => {
        if (!cancelled) setFacilities(unwrap(data))
      })
      .catch(() => {
        if (!cancelled) setFacilities([])
      })
    return () => {
      cancelled = true
    }
  }, [open])

  if (!open) return null

  const valid =
    name.trim().length > 0 && facility !== '' && startDate !== '' && endDate !== ''

  async function handleSubmit() {
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const payload = {
      name: name.trim(),
      facility,
      start_date: startDate,
      end_date: endDate,
      active,
    }

    const path = isEdit ? `/api/v1/hr/duty-rosters/${roster!.id}/` : '/api/v1/hr/duty-rosters/'

    try {
      const saved = await apiFetch<DutyRoster>(path, {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess?.(saved)
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const errors = extractFieldErrors(err.body)
        setFieldErrors(errors)
        setGlobalError(Object.values(errors)[0] ?? 'Erro ao salvar a escala.')
      } else {
        setGlobalError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const FieldError = ({ field }: { field: string }) =>
    fieldErrors[field] ? <p className="mt-1 text-xs text-red-600">{fieldErrors[field]}</p> : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-md flex-col rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">
            {isEdit ? 'Editar escala' : 'Nova escala'}
          </h2>
          <button
            onClick={onClose}
            disabled={submitting}
            className="text-slate-400 transition-colors hover:text-slate-600 disabled:opacity-40"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {globalError && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="text-sm text-red-700">{globalError}</p>
          </div>
        )}

        <div className="flex-1 space-y-4 overflow-y-auto">
          <div>
            <label htmlFor="roster_name" className={LABEL_CLASS}>
              Nome da escala <span className="text-red-500">*</span>
            </label>
            <input
              id="roster_name"
              type="text"
              className={INPUT_CLASS}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex.: Escala UTI — Agosto"
            />
            <FieldError field="name" />
          </div>

          <div>
            <label htmlFor="roster_facility" className={LABEL_CLASS}>
              Unidade (facility) <span className="text-red-500">*</span>
            </label>
            <select
              id="roster_facility"
              className={SELECT_CLASS}
              value={facility}
              onChange={(e) => setFacility(e.target.value)}
            >
              <option value="">Selecione...</option>
              {facilities.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
            <FieldError field="facility" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="roster_start" className={LABEL_CLASS}>
                Início <span className="text-red-500">*</span>
              </label>
              <input
                id="roster_start"
                type="date"
                className={INPUT_CLASS}
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
              <FieldError field="start_date" />
            </div>
            <div>
              <label htmlFor="roster_end" className={LABEL_CLASS}>
                Fim <span className="text-red-500">*</span>
              </label>
              <input
                id="roster_end"
                type="date"
                className={INPUT_CLASS}
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
              <FieldError field="end_date" />
            </div>
          </div>

          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-slate-700">Escala ativa</span>
          </label>
        </div>

        <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
          <button
            onClick={onClose}
            disabled={submitting}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={!valid || submitting}
            className="rounded-lg bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge px-4 py-2 text-sm font-medium text-white shadow-neu-btn-primary transition-all hover:shadow-neu-btn-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting
              ? 'Salvando...'
              : isEdit
                ? 'Salvar alterações'
                : 'Criar escala'}
          </button>
        </div>
      </div>
    </div>
  )
}
