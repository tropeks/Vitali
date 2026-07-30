'use client'

import { bedStatusMeta, formatLos, type BoardBed } from './inpatient-types'

interface BedCellProps {
  bed: BoardBed
  /** Active admission occupying this bed (from the census), when ocupado. */
  admissionId?: string | null
  losHours?: number | null
  canTransfer: boolean
  canDischarge: boolean
  canAdmit: boolean
  canRelease: boolean
  onTransfer?: (admissionId: string, bed: BoardBed) => void
  onDischarge?: (admissionId: string, bed: BoardBed) => void
  onAdmit?: (bed: BoardBed) => void
  onRelease?: (bed: BoardBed) => void
}

/**
 * A single bed on the mapa de leitos. Coloured by status (accessible map in
 * inpatient-types), showing the identifier and — when ocupado — the occupant
 * name + LOS. Per-status, per-permission action buttons: Transferir / Dar alta
 * on an occupied bed, Admitir on a livre bed.
 */
export default function BedCell({
  bed,
  admissionId,
  losHours,
  canTransfer,
  canDischarge,
  canAdmit,
  canRelease,
  onTransfer,
  onDischarge,
  onAdmit,
  onRelease,
}: BedCellProps) {
  const meta = bedStatusMeta(bed.status)
  const occupied = bed.status === 'ocupado'
  const free = bed.status === 'livre'
  const dirty = bed.status === 'higienizacao'

  return (
    <div className={`flex flex-col gap-1 rounded-lg border p-3 ${meta.cellClass}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-sm font-semibold">{bed.identifier}</span>
        <span className="rounded-full border border-current/40 px-2 py-0.5 text-[11px] font-semibold">
          {meta.label}
        </span>
      </div>

      {occupied && bed.patient && (
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={bed.patient.name}>
            {bed.patient.name}
          </p>
          {losHours != null && (
            <p className="text-xs opacity-80">Permanência: {formatLos(losHours)}</p>
          )}
        </div>
      )}

      <div className="mt-1 flex flex-wrap gap-1">
        {occupied && admissionId && canTransfer && (
          <button
            type="button"
            onClick={() => onTransfer?.(admissionId, bed)}
            className="rounded-md border border-current/40 bg-white/70 px-2 py-1 text-xs font-semibold hover:bg-white"
          >
            Transferir
          </button>
        )}
        {occupied && admissionId && canDischarge && (
          <button
            type="button"
            onClick={() => onDischarge?.(admissionId, bed)}
            className="rounded-md border border-current/40 bg-white/70 px-2 py-1 text-xs font-semibold hover:bg-white"
          >
            Dar alta
          </button>
        )}
        {free && canAdmit && (
          <button
            type="button"
            onClick={() => onAdmit?.(bed)}
            className="rounded-md border border-current/40 bg-white/70 px-2 py-1 text-xs font-semibold hover:bg-white"
          >
            Admitir
          </button>
        )}
        {dirty && canRelease && (
          <button
            type="button"
            onClick={() => onRelease?.(bed)}
            className="rounded-md border border-current/40 bg-white/70 px-2 py-1 text-xs font-semibold hover:bg-white"
          >
            Liberar
          </button>
        )}
      </div>
    </div>
  )
}
