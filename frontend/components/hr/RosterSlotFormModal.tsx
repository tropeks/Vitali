'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import type { DutyRoster } from './RosterFormModal'
import { SHIFT_LABELS, type RosterShift, type RosterSlot } from './RosterSlotGrid'

/**
 * RosterSlotFormModal — add a plantão (RosterSlot) to a roster. Mirrors the
 * RosterSlotRequest body: roster, date, shift, start_time, end_time,
 * professional | employee (at least one), unit. POST /api/v1/hr/roster-slots/.
 */

interface Option {
  id: string
  label: string
}

type Listish<T> = T[] | { results: T[] }

function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : (data?.results ?? [])
}

export interface RosterSlotFormModalProps {
  open: boolean
  roster: DutyRoster | null
  professionals?: Option[]
  employees?: Option[]
  onClose: () => void
  onSuccess?: (slot: RosterSlot) => void
}

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const SELECT_CLASS = `${INPUT_CLASS} bg-white`
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

const SHIFTS: RosterShift[] = ['morning', 'afternoon', 'night', 'full']

function extractFieldErrors(body: any): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [key, val] of Object.entries(body)) {
    if (Array.isArray(val) && val.length > 0) errors[key] = String(val[0])
    else if (typeof val === 'string') errors[key] = val
  }
  return errors
}

export default function RosterSlotFormModal({
  open,
  roster,
  professionals = [],
  employees = [],
  onClose,
  onSuccess,
}: RosterSlotFormModalProps) {
  const [date, setDate] = useState('')
  const [shift, setShift] = useState<RosterShift>('full')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [assignee, setAssignee] = useState('') // "professional:<id>" | "employee:<id>"
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')

  useEffect(() => {
    if (!open) return
    setDate(roster?.start_date ?? '')
    setShift('full')
    setStartTime('')
    setEndTime('')
    setAssignee('')
    setFieldErrors({})
    setGlobalError('')
  }, [open, roster])

  if (!open || !roster) return null

  const valid = date !== '' && startTime !== '' && endTime !== '' && assignee !== ''

  async function handleSubmit() {
    if (!roster) return
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const [kind, id] = assignee.split(':')
    const payload: Record<string, unknown> = {
      roster: roster.id,
      date,
      shift,
      start_time: startTime,
      end_time: endTime,
    }
    if (kind === 'professional') payload.professional = id
    else if (kind === 'employee') payload.employee = id

    try {
      const slot = await apiFetch<RosterSlot>('/api/v1/hr/roster-slots/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      onSuccess?.(slot)
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const errors = extractFieldErrors(err.body)
        setFieldErrors(errors)
        setGlobalError(Object.values(errors)[0] ?? 'Erro ao salvar o plantão.')
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
          <div>
            <h2 className="text-base font-semibold text-slate-900">Novo plantão</h2>
            <p className="mt-0.5 text-xs text-slate-500">{roster.name}</p>
          </div>
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
            <label htmlFor="slot_date" className={LABEL_CLASS}>
              Data <span className="text-red-500">*</span>
            </label>
            <input
              id="slot_date"
              type="date"
              className={INPUT_CLASS}
              value={date}
              min={roster.start_date}
              max={roster.end_date}
              onChange={(e) => setDate(e.target.value)}
            />
            <FieldError field="date" />
          </div>

          <div>
            <label htmlFor="slot_shift" className={LABEL_CLASS}>
              Turno
            </label>
            <select
              id="slot_shift"
              className={SELECT_CLASS}
              value={shift}
              onChange={(e) => setShift(e.target.value as RosterShift)}
            >
              {SHIFTS.map((s) => (
                <option key={s} value={s}>
                  {SHIFT_LABELS[s]}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="slot_start" className={LABEL_CLASS}>
                Início <span className="text-red-500">*</span>
              </label>
              <input
                id="slot_start"
                type="time"
                className={INPUT_CLASS}
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
              />
              <FieldError field="start_time" />
            </div>
            <div>
              <label htmlFor="slot_end" className={LABEL_CLASS}>
                Fim <span className="text-red-500">*</span>
              </label>
              <input
                id="slot_end"
                type="time"
                className={INPUT_CLASS}
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
              <FieldError field="end_time" />
            </div>
          </div>

          <div>
            <label htmlFor="slot_assignee" className={LABEL_CLASS}>
              Responsável <span className="text-red-500">*</span>
            </label>
            <select
              id="slot_assignee"
              className={SELECT_CLASS}
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="">Selecione...</option>
              {professionals.length > 0 && (
                <optgroup label="Profissionais">
                  {professionals.map((p) => (
                    <option key={`professional:${p.id}`} value={`professional:${p.id}`}>
                      {p.label}
                    </option>
                  ))}
                </optgroup>
              )}
              {employees.length > 0 && (
                <optgroup label="Funcionários">
                  {employees.map((e) => (
                    <option key={`employee:${e.id}`} value={`employee:${e.id}`}>
                      {e.label}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <FieldError field="professional" />
            <FieldError field="employee" />
          </div>
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
            {submitting ? 'Salvando...' : 'Adicionar plantão'}
          </button>
        </div>
      </div>
    </div>
  )
}
