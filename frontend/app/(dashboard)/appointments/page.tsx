'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import AppointmentModal from '@/components/appointments/AppointmentModal'

interface Appointment {
  id: string
  patient_name: string
  patient_mrn: string
  professional: string
  professional_name: string
  start_time: string
  end_time: string
  duration_minutes: number
  type: string
  type_display: string
  status: string
  status_display: string
  notes: string
}

interface Professional {
  id: string
  user_name: string
  specialty: string
}

const STATUS_COLORS: Record<string, string> = {
  scheduled: 'bg-blue-100 text-blue-800 border-blue-200',
  confirmed: 'bg-blue-500 text-white border-blue-600',
  waiting: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  in_progress: 'bg-green-100 text-green-800 border-green-200',
  completed: 'bg-slate-100 text-slate-600 border-slate-200',
  cancelled: 'bg-red-100 text-red-600 border-red-200',
  no_show: 'bg-red-100 text-red-600 border-red-200',
}

const HOURS = Array.from({ length: 21 }, (_, i) => {
  const h = 8 + Math.floor(i / 2)
  const m = i % 2 === 0 ? '00' : '30'
  return `${String(h).padStart(2, '0')}:${m}`
}).filter((h) => h <= '18:00')

function getWeekDates(base: Date): Date[] {
  const day = base.getDay() // 0=Sun
  const monday = new Date(base)
  monday.setDate(base.getDate() - ((day + 6) % 7))
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday)
    d.setDate(monday.getDate() + i)
    return d
  })
}

function isoDate(d: Date) {
  return d.toISOString().split('T')[0]
}

function formatDateLabel(d: Date) {
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}

function dayAbbr(d: Date) {
  return d.toLocaleDateString('pt-BR', { weekday: 'short' }).replace('.', '')
}

export default function AppointmentsPage() {
  const [weekBase, setWeekBase] = useState(() => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    return d
  })
  const [professionals, setProfessionals] = useState<Professional[]>([])
  const [selectedProfId, setSelectedProfId] = useState<string>('')
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalPrefill, setModalPrefill] = useState<{
    professionalId?: string
    date?: string
    slotStart?: string
    slotEnd?: string
  }>({})
  const [detailAppt, setDetailAppt] = useState<Appointment | null>(null)
  const [statusUpdating, setStatusUpdating] = useState(false)

  const weekDates = getWeekDates(weekBase)
  const weekStart = isoDate(weekDates[0])
  const weekEnd = isoDate(weekDates[6])

  // Load professionals
  useEffect(() => {
    fetch('/api/v1/professionals?ordering=user__full_name')
      .then((r) => r.json())
      .then((d) => {
        const list = d.results ?? d
        setProfessionals(list)
        if (list.length > 0 && !selectedProfId) setSelectedProfId(list[0].id)
      })
      .catch(() => {})
  }, [])

  const fetchAppointments = useCallback(async () => {
    setLoading(true)
    try {
      let url = `/api/v1/appointments?ordering=start_time`
      if (selectedProfId) url += `&professional_id=${selectedProfId}`
      // fetch the full week range via multiple date requests (API filters by date)
      // We fetch without date filter then filter client-side for the week
      const r = await fetch(url)
      const d = await r.json()
      const all: Appointment[] = d.results ?? d
      // Filter for current week
      const filtered = all.filter((a) => {
        const d = a.start_time.split('T')[0]
        return d >= weekStart && d <= weekEnd
      })
      setAppointments(filtered)
    } finally {
      setLoading(false)
    }
  }, [selectedProfId, weekStart, weekEnd])

  useEffect(() => {
    fetchAppointments()
  }, [fetchAppointments])

  const prevWeek = () => {
    const d = new Date(weekBase)
    d.setDate(d.getDate() - 7)
    setWeekBase(d)
  }
  const nextWeek = () => {
    const d = new Date(weekBase)
    d.setDate(d.getDate() + 7)
    setWeekBase(d)
  }
  const goToday = () => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    setWeekBase(d)
  }

  // Get appointments for a specific day + hour slot
  const getApptForSlot = (date: Date, hour: string) => {
    const dateStr = isoDate(date)
    return appointments.filter((a) => {
      const aDate = a.start_time.split('T')[0]
      const aTime = a.start_time.split('T')[1]?.slice(0, 5)
      return aDate === dateStr && aTime === hour
    })
  }

  const handleSlotClick = (date: Date, hour: string) => {
    const dateStr = isoDate(date)
    const [h, m] = hour.split(':')
    const slotStart = `${dateStr}T${hour}:00`
    const endH = m === '30' ? String(parseInt(h) + 1).padStart(2, '0') : h
    const endM = m === '30' ? '00' : '30'
    const slotEnd = `${dateStr}T${endH}:${endM}:00`
    setModalPrefill({ professionalId: selectedProfId, date: dateStr, slotStart, slotEnd })
    setShowModal(true)
  }

  const handleStatusChange = async (appt: Appointment, newStatus: string) => {
    setStatusUpdating(true)
    try {
      const r = await fetch(`/api/v1/appointments/${appt.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (r.ok) {
        setDetailAppt(null)
        fetchAppointments()
      }
    } finally {
      setStatusUpdating(false)
    }
  }

  const weekLabel = `${formatDateLabel(weekDates[0])} – ${formatDateLabel(weekDates[6])}/${weekDates[6].getFullYear()}`

  return (
    <div className="space-y-4 h-full flex flex-col">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Agenda</h1>
        </div>
        <div className="flex-1" />

        {/* Professional selector */}
        <select
          className="px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={selectedProfId}
          onChange={(e) => setSelectedProfId(e.target.value)}
        >
          <option value="">Todos os profissionais</option>
          {professionals.map((p) => (
            <option key={p.id} value={p.id}>
              {p.user_name}{p.specialty ? ` — ${p.specialty}` : ''}
            </option>
          ))}
        </select>

        {/* Week navigation */}
        <div className="flex items-center gap-1 border border-slate-200 rounded-lg overflow-hidden">
          <button
            onClick={prevWeek}
            className="p-2 hover:bg-slate-100 text-slate-600"
            title="Semana anterior"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={goToday}
            className="px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 font-medium"
          >
            {weekLabel}
          </button>
          <button
            onClick={nextWeek}
            className="p-2 hover:bg-slate-100 text-slate-600"
            title="Próxima semana"
          >
            <ChevronRight size={16} />
          </button>
        </div>

        <button
          onClick={() => { setModalPrefill({}); setShowModal(true) }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
        >
          <Plus size={16} />
          Agendar
        </button>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-xs">
        {[
          { status: 'scheduled', label: 'Agendado' },
          { status: 'confirmed', label: 'Confirmado' },
          { status: 'waiting', label: 'Aguardando' },
          { status: 'in_progress', label: 'Em atendimento' },
          { status: 'completed', label: 'Concluído' },
          { status: 'cancelled', label: 'Cancelado' },
        ].map(({ status, label }) => (
          <span key={status} className={`px-2 py-0.5 rounded-full border text-xs ${STATUS_COLORS[status]}`}>
            {label}
          </span>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="flex-1 bg-white border border-slate-200 rounded-xl overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
            Carregando agenda...
          </div>
        ) : (
          <table className="w-full text-xs border-collapse" style={{ minWidth: 700 }}>
            <thead className="sticky top-0 z-10 bg-white">
              <tr>
                <th className="w-14 border-b border-r border-slate-200 py-2 text-slate-400 font-normal" />
                {weekDates.map((d) => {
                  const isToday = isoDate(d) === isoDate(new Date())
                  return (
                    <th
                      key={d.toISOString()}
                      className={`border-b border-r border-slate-200 py-2 font-medium ${
                        isToday ? 'text-blue-600 bg-blue-50' : 'text-slate-700'
                      }`}
                    >
                      <div className="capitalize">{dayAbbr(d)}</div>
                      <div className={`text-base font-semibold ${isToday ? 'text-blue-600' : 'text-slate-900'}`}>
                        {d.getDate()}
                      </div>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {HOURS.map((hour) => (
                <tr key={hour} className="group">
                  <td className="border-r border-b border-slate-100 px-2 py-1 text-slate-400 text-right align-top w-14 font-mono">
                    {hour}
                  </td>
                  {weekDates.map((d) => {
                    const slotAppts = getApptForSlot(d, hour)
                    const isPast =
                      new Date(`${isoDate(d)}T${hour}:00`) < new Date()
                    return (
                      <td
                        key={d.toISOString()}
                        className={`border-r border-b border-slate-100 p-0.5 align-top h-10 cursor-pointer ${
                          isPast ? 'bg-slate-50/50' : 'hover:bg-blue-50/50'
                        }`}
                        onClick={() => !isPast && slotAppts.length === 0 && handleSlotClick(d, hour)}
                      >
                        {slotAppts.map((appt) => (
                          <button
                            key={appt.id}
                            className={`w-full text-left px-1.5 py-1 rounded border text-xs leading-tight truncate ${
                              STATUS_COLORS[appt.status] ?? 'bg-slate-100 text-slate-700 border-slate-200'
                            }`}
                            onClick={(e) => { e.stopPropagation(); setDetailAppt(appt) }}
                            title={`${appt.patient_name} — ${appt.type_display}`}
                          >
                            <div className="font-medium truncate">{appt.patient_name}</div>
                            <div className="opacity-70 truncate">{appt.type_display}</div>
                          </button>
                        ))}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Appointment detail panel */}
      {detailAppt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
              <h2 className="text-lg font-semibold text-slate-900">Detalhes do Agendamento</h2>
              <button
                onClick={() => setDetailAppt(null)}
                className="text-slate-400 hover:text-slate-700 rounded-lg p-1"
              >
                ✕
              </button>
            </div>
            <div className="px-6 py-4 space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-slate-500 text-xs">Paciente</p>
                  <p className="font-medium">{detailAppt.patient_name}</p>
                  <p className="text-xs text-slate-400">{detailAppt.patient_mrn}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs">Profissional</p>
                  <p className="font-medium">{detailAppt.professional_name}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs">Horário</p>
                  <p className="font-medium">
                    {new Date(detailAppt.start_time).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                    {' – '}
                    {new Date(detailAppt.end_time).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                  </p>
                  <p className="text-xs text-slate-400">{detailAppt.duration_minutes} min</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs">Tipo</p>
                  <p className="font-medium">{detailAppt.type_display}</p>
                </div>
              </div>
              <div>
                <p className="text-slate-500 text-xs mb-1">Status</p>
                <span className={`inline-block px-2 py-0.5 rounded-full text-xs border ${STATUS_COLORS[detailAppt.status]}`}>
                  {detailAppt.status_display}
                </span>
              </div>
              {detailAppt.notes && (
                <div>
                  <p className="text-slate-500 text-xs">Observações</p>
                  <p className="text-slate-700">{detailAppt.notes}</p>
                </div>
              )}

              {/* Status actions */}
              <div className="border-t border-slate-100 pt-3">
                <p className="text-slate-500 text-xs mb-2">Mudar status</p>
                <div className="flex flex-wrap gap-2">
                  {[
                    { value: 'confirmed', label: 'Confirmar' },
                    { value: 'waiting', label: 'Aguardando' },
                    { value: 'in_progress', label: 'Iniciar' },
                    { value: 'completed', label: 'Concluir' },
                    { value: 'no_show', label: 'Não compareceu' },
                    { value: 'cancelled', label: 'Cancelar' },
                  ]
                    .filter((s) => s.value !== detailAppt.status)
                    .map((s) => (
                      <button
                        key={s.value}
                        disabled={statusUpdating}
                        onClick={() => handleStatusChange(detailAppt, s.value)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50 ${STATUS_COLORS[s.value]}`}
                      >
                        {s.label}
                      </button>
                    ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Appointment modal */}
      {showModal && (
        <AppointmentModal
          prefillProfessionalId={modalPrefill.professionalId}
          prefillDate={modalPrefill.date}
          prefillSlotStart={modalPrefill.slotStart}
          prefillSlotEnd={modalPrefill.slotEnd}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false)
            fetchAppointments()
          }}
        />
      )}
    </div>
  )
}
