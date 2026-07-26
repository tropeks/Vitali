'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import RosterList from '@/components/hr/RosterList'
import RosterFormModal, { type DutyRoster } from '@/components/hr/RosterFormModal'
import RosterSlotFormModal from '@/components/hr/RosterSlotFormModal'
import type { RosterSlot } from '@/components/hr/RosterSlotGrid'

type Listish<T> = T[] | { results: T[] }

function unwrap<T>(data: Listish<T>): T[] {
  return Array.isArray(data) ? data : ((data as { results: T[] })?.results ?? [])
}

interface Named {
  id: string
  name?: string
  full_name?: string
  user_name?: string
}

const PRIMARY_BTN =
  'px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all'

export default function EscalasPage() {
  const [rosters, setRosters] = useState<DutyRoster[]>([])
  const [slots, setSlots] = useState<RosterSlot[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Reference name maps (best-effort — never block the page).
  const [facilityNames, setFacilityNames] = useState<Record<string, string>>({})
  const [professionalNames, setProfessionalNames] = useState<Record<string, string>>({})
  const [employeeNames, setEmployeeNames] = useState<Record<string, string>>({})

  // Modal state
  const [formOpen, setFormOpen] = useState(false)
  const [editingRoster, setEditingRoster] = useState<DutyRoster | null>(null)
  const [slotRoster, setSlotRoster] = useState<DutyRoster | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [rostersData, slotsData] = await Promise.all([
        apiFetch<Listish<DutyRoster>>('/api/v1/hr/duty-rosters/'),
        apiFetch<Listish<RosterSlot>>('/api/v1/hr/roster-slots/'),
      ])
      setRosters(unwrap(rostersData))
      setSlots(unwrap(slotsData))
    } catch {
      setError('Erro ao carregar escalas.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Best-effort reference data for human-readable labels.
  useEffect(() => {
    let cancelled = false
    async function loadRefs() {
      try {
        const [facilities, professionals, employees] = await Promise.all([
          apiFetch<Listish<Named>>('/api/v1/organization/facilities/').catch(() => []),
          apiFetch<Listish<Named>>('/api/v1/professionals/').catch(() => []),
          apiFetch<Listish<Named>>('/api/v1/hr/employees/').catch(() => []),
        ])
        if (cancelled) return
        setFacilityNames(
          Object.fromEntries(unwrap(facilities).map((f) => [f.id, f.name ?? 'Unidade']))
        )
        setProfessionalNames(
          Object.fromEntries(
            unwrap(professionals).map((p) => [p.id, p.user_name ?? p.full_name ?? p.name ?? 'Profissional'])
          )
        )
        setEmployeeNames(
          Object.fromEntries(
            unwrap(employees).map((e) => [e.id, e.full_name ?? e.name ?? 'Funcionário'])
          )
        )
      } catch {
        /* labels are optional */
      }
    }
    loadRefs()
    return () => {
      cancelled = true
    }
  }, [])

  const slotsByRoster = useMemo(() => {
    const map: Record<string, RosterSlot[]> = {}
    for (const slot of slots) {
      const bucket = map[slot.roster]
      if (bucket) bucket.push(slot)
      else map[slot.roster] = [slot]
    }
    return map
  }, [slots])

  const professionalOptions = useMemo(
    () => Object.entries(professionalNames).map(([id, label]) => ({ id, label })),
    [professionalNames]
  )
  const employeeOptions = useMemo(
    () => Object.entries(employeeNames).map(([id, label]) => ({ id, label })),
    [employeeNames]
  )

  function openCreate() {
    setEditingRoster(null)
    setFormOpen(true)
  }

  function openEdit(roster: DutyRoster) {
    setEditingRoster(roster)
    setFormOpen(true)
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Escalas</h1>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Gerencie as escalas de plantão da equipe assistencial.
          </p>
        </div>
        <button onClick={openCreate} className={PRIMARY_BTN}>
          + Nova escala
        </button>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar escalas."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && rosters.length === 0 && (
        <SectionState
          title="Nenhuma escala cadastrada ainda."
          detail="Crie a primeira escala para organizar os plantões da sua equipe."
          action={
            <button onClick={openCreate} className={PRIMARY_BTN}>
              + Nova escala
            </button>
          }
        />
      )}

      {!loading && !error && rosters.length > 0 && (
        <RosterList
          rosters={rosters}
          slotsByRoster={slotsByRoster}
          facilityNames={facilityNames}
          professionalNames={professionalNames}
          employeeNames={employeeNames}
          onEdit={openEdit}
          onAddSlot={(roster) => setSlotRoster(roster)}
        />
      )}

      <RosterFormModal
        open={formOpen}
        roster={editingRoster}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          load()
        }}
      />

      <RosterSlotFormModal
        open={slotRoster !== null}
        roster={slotRoster}
        professionals={professionalOptions}
        employees={employeeOptions}
        onClose={() => setSlotRoster(null)}
        onSuccess={() => {
          setSlotRoster(null)
          load()
        }}
      />
    </PageShell>
  )
}
