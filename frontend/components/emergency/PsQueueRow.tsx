'use client'

import { AlertTriangle, Clock } from 'lucide-react'
import {
  acuityMeta,
  canClassifyStatus,
  canCloseStatus,
  canStartAttendanceStatus,
  formatArrival,
  formatWaited,
  modeOfArrivalLabel,
  statusLabel,
  type QueueRow,
} from './ps-board-types'

interface PsQueueRowProps {
  row: QueueRow
  canManage: boolean
  canClassify: boolean
  onClassify: (row: QueueRow) => void
  onStartAttendance: (row: QueueRow) => void
  onClose: (row: QueueRow) => void
}

/**
 * A single PS queue row (boletim) coloured by its Manchester acuidade — neutral
 * grey while unclassified — with the patient, queixa, meio de chegada, tempo de
 * espera and an `overdue` (tempo-alvo estourado) highlight. Per-permission
 * actions: Classificar (emergency.classify), Chamar (emergency.manage,
 * classificado→em_atendimento) e Desfecho (emergency.manage).
 */
export default function PsQueueRow({
  row,
  canManage,
  canClassify,
  onClassify,
  onStartAttendance,
  onClose,
}: PsQueueRowProps) {
  const meta = acuityMeta(row.acuity_level)
  const showClassify = canClassify && canClassifyStatus(row.status)
  const showStart = canManage && canStartAttendanceStatus(row.status)
  const showClose = canManage && canCloseStatus(row.status)

  return (
    <li
      aria-label={`Boletim de ${row.patient.name}`}
      className={`flex items-stretch gap-0 overflow-hidden rounded-xl border ${meta.rowClass} ${
        row.overdue ? 'ring-2 ring-red-400' : ''
      }`}
    >
      {/* Acuity accent bar */}
      <span aria-hidden className={`w-1.5 shrink-0 ${meta.accentClass}`} />

      <div className="flex flex-1 flex-wrap items-center justify-between gap-3 px-3 py-2.5">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-neu-ink">{row.patient.name}</span>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${meta.badgeClass}`}
            >
              {meta.label}
            </span>
            {row.overdue && (
              <span className="inline-flex items-center gap-1 rounded-full border border-red-400 bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-800">
                <AlertTriangle size={11} aria-hidden />
                Tempo-alvo estourado
              </span>
            )}
          </div>
          <p className="truncate text-xs text-neu-inkMuted">
            {row.chief_complaint || 'Sem queixa registrada'}
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-neu-inkMuted">
            <span>{modeOfArrivalLabel(row.mode_of_arrival)}</span>
            <span className="inline-flex items-center gap-1">
              <Clock size={11} aria-hidden />
              Espera: {formatWaited(row.waited_minutes)}
            </span>
            <span>Chegada: {formatArrival(row.arrival_at)}</span>
            {row.target_minutes != null && <span>Alvo: {formatWaited(row.target_minutes)}</span>}
            <span>{statusLabel(row.status)}</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {showClassify && (
            <button
              type="button"
              onClick={() => onClassify(row)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-neu-ink hover:bg-slate-50"
            >
              Classificar
            </button>
          )}
          {showStart && (
            <button
              type="button"
              onClick={() => onStartAttendance(row)}
              className="rounded-lg bg-neu-brand px-2.5 py-1.5 text-xs font-semibold text-white hover:opacity-90"
            >
              Chamar
            </button>
          )}
          {showClose && (
            <button
              type="button"
              onClick={() => onClose(row)}
              className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-neu-ink hover:bg-slate-50"
            >
              Desfecho
            </button>
          )}
        </div>
      </div>
    </li>
  )
}
