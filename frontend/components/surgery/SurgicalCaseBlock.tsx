'use client'

import { CheckCircle2, Clock, Stethoscope, User, XCircle } from 'lucide-react'
import {
  canCancelCase,
  canConfirmCase,
  canRescheduleCase,
  caseStatusMeta,
  formatWindow,
  priorityMeta,
  type BoardCase,
} from './surgery-board-types'

interface SurgicalCaseBlockProps {
  surgicalCase: BoardCase
  canSchedule: boolean
  onConfirm: (c: BoardCase) => void
  onReschedule: (c: BoardCase) => void
  onCancel: (c: BoardCase) => void
}

/**
 * A single scheduled case rendered as a block in a room column. Coloured by
 * `status` (CASE_STATUS_META) with a left accent for urgência/emergência. Shows
 * patient, surgeon, the scheduled window and a procedures-count summary. The
 * lifecycle actions (Confirmar / Reagendar / Cancelar) are gated by
 * `canSchedule` AND by the case status (only the transitions the backend allows).
 */
export default function SurgicalCaseBlock({
  surgicalCase,
  canSchedule,
  onConfirm,
  onReschedule,
  onCancel,
}: SurgicalCaseBlockProps) {
  const status = caseStatusMeta(surgicalCase.status)
  const priority = priorityMeta(surgicalCase.priority)
  const procCount = surgicalCase.procedures.length
  const showConfirm = canSchedule && canConfirmCase(surgicalCase.status)
  const showReschedule = canSchedule && canRescheduleCase(surgicalCase.status)
  const showCancel = canSchedule && canCancelCase(surgicalCase.status)

  return (
    <article
      aria-label={`Cirurgia de ${surgicalCase.patient.name}`}
      className={`rounded-lg border p-2.5 text-xs shadow-sm ${status.blockClass} ${
        priority.accent ? 'border-l-4 border-l-red-500' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 font-semibold">
          <Clock size={12} aria-hidden />
          {formatWindow(surgicalCase.scheduled_start, surgicalCase.scheduled_end)}
        </span>
        <span
          className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${status.badgeClass}`}
        >
          {status.label}
        </span>
      </div>

      <p className="mt-1.5 flex items-center gap-1 font-semibold text-neu-ink">
        <User size={12} aria-hidden />
        {surgicalCase.patient.name}
      </p>
      <p className="mt-0.5 flex items-center gap-1 text-neu-inkMuted">
        <Stethoscope size={12} aria-hidden />
        {surgicalCase.surgeon.name}
      </p>

      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        {priority.accent && (
          <span
            className={`rounded-full border px-1.5 py-0.5 text-[10px] font-semibold ${priority.badgeClass}`}
          >
            {priority.label}
          </span>
        )}
        <span className="text-[11px] text-neu-inkMuted">
          {procCount === 1 ? '1 procedimento' : `${procCount} procedimentos`}
        </span>
      </div>

      {(showConfirm || showReschedule || showCancel) && (
        <div className="mt-2 flex flex-wrap gap-1.5 border-t border-white/60 pt-2">
          {showConfirm && (
            <button
              type="button"
              onClick={() => onConfirm(surgicalCase)}
              className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-blue-700"
            >
              <CheckCircle2 size={12} aria-hidden />
              Confirmar
            </button>
          )}
          {showReschedule && (
            <button
              type="button"
              onClick={() => onReschedule(surgicalCase)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50"
            >
              <Clock size={12} aria-hidden />
              Reagendar
            </button>
          )}
          {showCancel && (
            <button
              type="button"
              onClick={() => onCancel(surgicalCase)}
              className="inline-flex items-center gap-1 rounded-md border border-red-300 bg-white px-2 py-1 text-[11px] font-semibold text-red-700 hover:bg-red-50"
            >
              <XCircle size={12} aria-hidden />
              Cancelar
            </button>
          )}
        </div>
      )}
    </article>
  )
}
