'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import BedCell from './BedCell'
import TransferBedModal from './TransferBedModal'
import DischargeModal from './DischargeModal'
import ReleaseBedModal from './ReleaseBedModal'
import {
  isFreeBed,
  type BoardBed,
  type BoardResponse,
  type BoardUnit,
  type CensusResponse,
  type CensusRow,
} from './inpatient-types'

interface BedBoardProps {
  canTransfer: boolean
  canDischarge: boolean
  canAdmit: boolean
  canRelease: boolean
  /** Bumping this (from the page) forces a reload after a census-side action. */
  reloadToken?: number
  /** Notify the page that ADT state changed so the census can refresh too. */
  onChanged?: () => void
}

interface ActiveAdmission {
  admissionId: string
  losHours: number
}

/** bed_id → active admission occupying it (id + LOS), from the census. */
function admissionByBed(census: CensusRow[]): Record<string, ActiveAdmission> {
  const map: Record<string, ActiveAdmission> = {}
  for (const row of census) {
    map[row.bed.id] = { admissionId: row.admission_id, losHours: row.los_hours }
  }
  return map
}

/**
 * Mapa de leitos (bed-board) — grid grouped por unidade, each bed coloured by
 * status. Consumes GET /beds/board/ for the physical map and GET
 * /admissions/census/ to resolve the active admission (id/LOS) behind each
 * occupied bed. Bed actions (Transferir / Dar alta) are gated by permission.
 */
export default function BedBoard({
  canTransfer,
  canDischarge,
  canAdmit,
  canRelease,
  reloadToken = 0,
  onChanged,
}: BedBoardProps) {
  const [units, setUnits] = useState<BoardUnit[]>([])
  const [census, setCensus] = useState<CensusRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [transferFor, setTransferFor] = useState<{
    admissionId: string
    patientName: string
  } | null>(null)
  const [dischargeFor, setDischargeFor] = useState<{
    admissionId: string
    patientName: string
  } | null>(null)
  const [releaseFor, setReleaseFor] = useState<{
    bedId: string
    bedIdentifier: string
  } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const [board, censusResp] = await Promise.all([
        apiFetch<BoardResponse>('/api/v1/beds/board/'),
        apiFetch<CensusResponse>('/api/v1/admissions/census/'),
      ])
      setUnits(board?.units ?? [])
      setCensus(censusResp?.census ?? [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, reloadToken])

  const byBed = useMemo(() => admissionByBed(census), [census])

  /** Every livre bed across all units — candidate transfer destinations. */
  const freeBeds = useMemo<BoardBed[]>(
    () => units.flatMap((u) => u.rooms.flatMap((r) => r.beds.filter(isFreeBed))),
    [units]
  )

  const afterAction = useCallback(() => {
    setTransferFor(null)
    setDischargeFor(null)
    setReleaseFor(null)
    onChanged?.()
    load()
  }, [load, onChanged])

  function openTransfer(admissionId: string, bed: BoardBed) {
    setTransferFor({ admissionId, patientName: bed.patient?.name ?? 'Paciente' })
  }
  function openDischarge(admissionId: string, bed: BoardBed) {
    setDischargeFor({ admissionId, patientName: bed.patient?.name ?? 'Paciente' })
  }
  function openRelease(bed: BoardBed) {
    setReleaseFor({ bedId: bed.id, bedIdentifier: bed.identifier })
  }

  if (loading) {
    return (
      <SectionState title="Carregando mapa de leitos..." detail="Buscando a ocupação dos leitos." />
    )
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar o mapa de leitos"
        detail="Não foi possível carregar a ocupação dos leitos. Tente novamente."
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

  const totalBeds = units.reduce(
    (sum, u) => sum + u.rooms.reduce((rs, r) => rs + r.beds.length, 0),
    0
  )

  if (totalBeds === 0) {
    return (
      <SectionState
        title="Nenhum leito cadastrado"
        detail="Cadastre unidades, quartos e leitos na gestão de leitos para ver o mapa."
      />
    )
  }

  return (
    <div className="space-y-6">
      {units.map((unit) => {
        const unitBeds = unit.rooms.flatMap((r) => r.beds)
        return (
          <section key={unit.id} aria-label={`Unidade ${unit.name}`}>
            <div className="mb-2 flex items-baseline gap-2">
              <h3 className="text-sm font-semibold text-neu-ink">{unit.name}</h3>
              <span className="font-mono text-xs text-neu-inkMuted">{unit.code}</span>
            </div>
            {unitBeds.length === 0 ? (
              <p className="text-xs text-neu-inkMuted">Sem leitos nesta unidade.</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
                {unitBeds.map((bed) => {
                  const active = byBed[bed.id]
                  return (
                    <BedCell
                      key={bed.id}
                      bed={bed}
                      admissionId={active?.admissionId}
                      losHours={active?.losHours}
                      canTransfer={canTransfer}
                      canDischarge={canDischarge}
                      canAdmit={canAdmit}
                      canRelease={canRelease}
                      onTransfer={openTransfer}
                      onDischarge={openDischarge}
                      onRelease={openRelease}
                    />
                  )
                })}
              </div>
            )}
          </section>
        )
      })}

      {transferFor && (
        <TransferBedModal
          admissionId={transferFor.admissionId}
          patientName={transferFor.patientName}
          freeBeds={freeBeds}
          onClose={() => setTransferFor(null)}
          onTransferred={afterAction}
        />
      )}
      {dischargeFor && (
        <DischargeModal
          admissionId={dischargeFor.admissionId}
          patientName={dischargeFor.patientName}
          onClose={() => setDischargeFor(null)}
          onDischarged={afterAction}
        />
      )}
      {releaseFor && (
        <ReleaseBedModal
          bedId={releaseFor.bedId}
          bedIdentifier={releaseFor.bedIdentifier}
          onClose={() => setReleaseFor(null)}
          onReleased={afterAction}
        />
      )}
    </div>
  )
}
