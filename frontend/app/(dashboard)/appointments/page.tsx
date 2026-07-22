'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock,
  LayoutGrid,
  ListChecks,
  PlayCircle,
  Plus,
  RefreshCw,
  UserCheck,
  XCircle,
} from 'lucide-react'
import AppointmentModal from '@/components/appointments/AppointmentModal'
import PIXModal from '@/components/appointments/PIXModal'
import { apiFetch } from '@/lib/api'
import {
  appointmentBadgeLabel,
  formatPtTime,
  getAppointmentStatusMeta,
  TONE_CLASSES,
  type OperationalTone,
} from '@/lib/operational-ui'
import { KpiTile, PageShell } from '@/components/shared'
import RemoteCombobox from '@/components/shared/RemoteCombobox'

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
  notes?: string | null
  whatsapp_reminder_sent: boolean
  whatsapp_confirmed: boolean
  arrived_at: string | null
  started_at: string | null
}

interface Professional {
  id: string
  user_name: string
  specialty: string
}

type AppointmentAction = 'check-in' | 'start' | 'confirmed' | 'completed' | 'no_show' | 'cancelled'

const HOURS = Array.from({ length: 21 }, (_, i) => {
  const h = 8 + Math.floor(i / 2)
  const m = i % 2 === 0 ? '00' : '30'
  return `${String(h).padStart(2, '0')}:${m}`
}).filter((h) => h <= '18:00')

const QUEUE_STATUSES = new Set(['scheduled', 'confirmed', 'waiting', 'in_progress'])
const TERMINAL_STATUSES = new Set(['completed', 'cancelled', 'no_show'])

function getWeekDates(base: Date): Date[] {
  const day = base.getDay()
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

function formatDayLong(d: Date) {
  return d.toLocaleDateString('pt-BR', {
    weekday: 'long',
    day: '2-digit',
    month: 'long',
  })
}

function formatTimeRange(appt: Appointment) {
  return `${formatPtTime(appt.start_time)} - ${formatPtTime(appt.end_time)}`
}

function getList<T>(payload: T[] | { results?: T[] } | null | undefined): T[] {
  if (Array.isArray(payload)) return payload
  return payload?.results ?? []
}

function minutesBetween(start: string | null | undefined, end: Date) {
  if (!start) return null
  const value = Math.round((end.getTime() - new Date(start).getTime()) / 60_000)
  return Math.max(0, value)
}

function getLateMinutes(appt: Appointment, now: Date | null) {
  if (!now || TERMINAL_STATUSES.has(appt.status) || appt.status === 'in_progress') return null
  const value = Math.round((now.getTime() - new Date(appt.start_time).getTime()) / 60_000)
  return value > 0 ? value : null
}

function getWaitMinutes(appt: Appointment, now: Date | null) {
  if (!now) return null
  if (appt.arrived_at) return minutesBetween(appt.arrived_at, now)
  if (appt.status === 'waiting') return minutesBetween(appt.start_time, now)
  return null
}

function getQueueTone(appt: Appointment, now: Date | null): OperationalTone {
  if (appt.status === 'in_progress') return 'success'
  const waitMin = getWaitMinutes(appt, now)
  if (waitMin != null && waitMin >= 30) return 'critical'
  if (waitMin != null) return 'attention'
  const lateMin = getLateMinutes(appt, now)
  if (lateMin != null && lateMin >= 10) return 'critical'
  if (lateMin != null) return 'attention'
  if (appt.status === 'confirmed') return 'info'
  return 'neutral'
}

function getQueueSignal(appt: Appointment, now: Date | null) {
  if (appt.status === 'in_progress') return 'Em atendimento'
  const waitMin = getWaitMinutes(appt, now)
  if (waitMin != null) return `${waitMin} min de espera`
  const lateMin = getLateMinutes(appt, now)
  if (lateMin != null) return `${lateMin} min de atraso`
  if (appt.whatsapp_confirmed) return 'Confirmado no WhatsApp'
  if (appt.whatsapp_reminder_sent) return 'Lembrete enviado'
  return getAppointmentStatusMeta(appt.status).label
}

function queuePriority(appt: Appointment, now: Date | null) {
  const tone = getQueueTone(appt, now)
  const lateMin = getLateMinutes(appt, now) ?? 0
  const waitMin = getWaitMinutes(appt, now) ?? 0
  if (tone === 'critical') return 0
  if (appt.status === 'waiting') return 1
  if (appt.status === 'in_progress') return 2
  if (lateMin > 0 || waitMin > 0) return 3
  if (appt.status === 'confirmed') return 4
  return 5
}

function ActionSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg border border-slate-100 bg-slate-50" />
      ))}
    </div>
  )
}

export default function AppointmentsPage() {
  const router = useRouter()
  const [weekBase, setWeekBase] = useState(() => {
    const d = new Date()
    d.setHours(0, 0, 0, 0)
    return d
  })
  const [clientNow, setClientNow] = useState<Date | null>(null)
  const [selectedProfessional, setSelectedProfessional] = useState<Professional | null>(null)
  const [selectedProfId, setSelectedProfId] = useState<string>('')
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [todayAppointments, setTodayAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [modalPrefill, setModalPrefill] = useState<{
    professionalId?: string
    date?: string
    slotStart?: string
    slotEnd?: string
  }>({})
  const [detailAppt, setDetailAppt] = useState<Appointment | null>(null)
  const [actionUpdating, setActionUpdating] = useState<string | null>(null)
  const [pixAppt, setPixAppt] = useState<Appointment | null>(null)

  const weekDates = getWeekDates(weekBase)
  const weekStart = isoDate(weekDates[0])
  const weekEnd = isoDate(weekDates[6])

  useEffect(() => {
    const tick = () => setClientNow(new Date())
    tick()
    const interval = setInterval(tick, 60_000)
    return () => clearInterval(interval)
  }, [])

  const fetchAppointments = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let url = `/api/v1/appointments/?ordering=start_time`
      if (selectedProfId) url += `&professional_id=${selectedProfId}`
      const [weekPayload, todayPayload] = await Promise.all([
        apiFetch<Appointment[] | { results?: Appointment[] }>(url),
        apiFetch<Appointment[]>('/api/v1/appointments/today/'),
      ])
      const weekItems = getList<Appointment>(weekPayload).filter((appt) => {
        const date = appt.start_time.split('T')[0]
        return date >= weekStart && date <= weekEnd
      })
      const todayItems = getList<Appointment>(todayPayload).filter((appt) => (
        selectedProfId ? appt.professional === selectedProfId : true
      ))
      setAppointments(weekItems)
      setTodayAppointments(todayItems)
      setLastUpdated(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível carregar a agenda.')
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

  const getApptForSlot = (date: Date, hour: string) => {
    const dateStr = isoDate(date)
    return appointments.filter((appt) => {
      const aDate = appt.start_time.split('T')[0]
      const aTime = appt.start_time.split('T')[1]?.slice(0, 5)
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

  const runAppointmentAction = async (appt: Appointment, action: AppointmentAction) => {
    setActionUpdating(`${appt.id}:${action}`)
    setActionError(null)
    try {
      if (action === 'check-in') {
        await apiFetch(`/api/v1/appointments/${appt.id}/check-in/`, { method: 'POST' })
        setDetailAppt(null)
        await fetchAppointments()
        return
      }
      if (action === 'start') {
        const data = await apiFetch<{ encounter_id?: string }>(`/api/v1/appointments/${appt.id}/start/`, {
          method: 'POST',
        })
        setDetailAppt(null)
        if (data.encounter_id) {
          router.push(`/encounters/${data.encounter_id}`)
          return
        }
        await fetchAppointments()
        return
      }
      await apiFetch(`/api/v1/appointments/${appt.id}/status/`, {
        method: 'PATCH',
        body: JSON.stringify({ status: action }),
      })
      setDetailAppt(null)
      await fetchAppointments()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Não foi possível atualizar o agendamento.')
    } finally {
      setActionUpdating(null)
    }
  }

  const isUpdating = (appt: Appointment) => actionUpdating?.startsWith(`${appt.id}:`) ?? false

  const queueAppointments = useMemo(
    () => todayAppointments
      .filter((appt) => QUEUE_STATUSES.has(appt.status))
      .sort((a, b) => {
        const priority = queuePriority(a, clientNow) - queuePriority(b, clientNow)
        if (priority !== 0) return priority
        return a.start_time.localeCompare(b.start_time)
      }),
    [todayAppointments, clientNow]
  )

  const completedToday = todayAppointments.filter((appt) => appt.status === 'completed').length
  const inProgressToday = todayAppointments.filter((appt) => appt.status === 'in_progress').length
  const terminalFriction = todayAppointments.filter((appt) => ['cancelled', 'no_show'].includes(appt.status)).length
  const delayedToday = todayAppointments.filter((appt) => {
    const lateMin = getLateMinutes(appt, clientNow)
    const waitMin = getWaitMinutes(appt, clientNow)
    return (lateMin != null && lateMin >= 10) || (waitMin != null && waitMin >= 30)
  }).length
  const checkedInToday = todayAppointments.filter((appt) => appt.arrived_at || appt.status === 'waiting').length
  const nextAction = queueAppointments[0] ?? null
  const todayLabel = clientNow ? formatDayLong(clientNow) : 'Hoje'
  const weekLabel = `${formatDateLabel(weekDates[0])} - ${formatDateLabel(weekDates[6])}/${weekDates[6].getFullYear()}`

  const queueRows = queueAppointments.map((appt) => {
    const meta = getAppointmentStatusMeta(appt.status)
    const tone = getQueueTone(appt, clientNow)
    const disabled = isUpdating(appt)
    const terminal = TERMINAL_STATUSES.has(appt.status)
    const signal = getQueueSignal(appt, clientNow)
    const startLabel = appt.status === 'in_progress' ? 'Abrir atendimento' : 'Iniciar atendimento'
    return (
      <tr key={appt.id} className={`border-l-4 ${meta.borderClass} ${meta.rowClass}`}>
        <td className="px-3 py-3 font-mono text-xs text-slate-600">{formatTimeRange(appt)}</td>
        <td className="px-3 py-3">
          <button
            onClick={() => setDetailAppt(appt)}
            className="text-left font-semibold text-slate-900 hover:text-blue-700"
          >
            {appt.patient_name}
          </button>
          <p className="mt-0.5 font-mono text-[11px] text-slate-500">{appt.patient_mrn}</p>
        </td>
        <td className="px-3 py-3 text-sm text-slate-600">{appt.professional_name}</td>
        <td className="px-3 py-3 text-sm text-slate-500">{appt.type_display}</td>
        <td className="px-3 py-3">
          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}>
            {appointmentBadgeLabel(appt.status, appt.status_display)}
          </span>
        </td>
        <td className="px-3 py-3">
          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE_CLASSES[tone]}`}>
            {signal}
          </span>
        </td>
        <td className="px-3 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              disabled={disabled || Boolean(appt.arrived_at) || appt.status === 'in_progress' || terminal}
              onClick={() => runAppointmentAction(appt, 'check-in')}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-100 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-200 disabled:opacity-40"
            >
              <UserCheck size={12} />
              Registrar chegada
            </button>
            <button
              disabled={disabled || terminal}
              onClick={() => runAppointmentAction(appt, 'start')}
              className="inline-flex items-center gap-1 rounded-lg bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700 hover:bg-green-200 disabled:opacity-40"
            >
              <PlayCircle size={12} />
              {startLabel}
            </button>
            <button
              disabled={disabled}
              onClick={() => setPixAppt(appt)}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1 block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide hover:bg-slate-200 disabled:opacity-40"
            >
              <CircleDollarSign size={12} />
              PIX
            </button>
            <button
              disabled={disabled || terminal}
              onClick={() => runAppointmentAction(appt, 'no_show')}
              className="inline-flex items-center gap-1 rounded-lg bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-600 hover:bg-red-100 disabled:opacity-40"
            >
              <XCircle size={12} />
              Faltou
            </button>
          </div>
        </td>
      </tr>
    )
  })

  return (
    <PageShell variant="operational">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Agenda Operacional</h1>
          <p className="mt-1 text-sm text-slate-500">
            {todayLabel.charAt(0).toUpperCase() + todayLabel.slice(1)} · {queueAppointments.length} na fila ativa
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[260px]">
            <RemoteCombobox<Professional>
              label="Filtrar profissional"
              endpoint="/api/v1/professionals/?ordering=user__full_name"
              value={selectedProfessional}
              getKey={(professional) => professional.id}
              getLabel={(professional) => `${professional.user_name}${professional.specialty ? ` — ${professional.specialty}` : ''}`}
              onChange={(professional) => {
                setSelectedProfessional(professional)
                setSelectedProfId(professional?.id ?? '')
              }}
              placeholder="Buscar profissional..."
              allLabel="Todos os profissionais"
            />
          </div>

          <div className="flex items-center overflow-hidden rounded-lg border border-slate-200 bg-white">
            <button onClick={prevWeek} className="p-2 text-slate-600 hover:bg-slate-50" title="Semana anterior">
              <ChevronLeft size={16} />
            </button>
            <button onClick={goToday} className="px-3 py-2 block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide hover:bg-slate-50">
              {weekLabel}
            </button>
            <button onClick={nextWeek} className="p-2 text-slate-600 hover:bg-slate-50" title="Próxima semana">
              <ChevronRight size={16} />
            </button>
          </div>

          <button
            onClick={() => router.push('/waiting-room')}
            className="inline-flex items-center gap-2 neu-btn-secondary"
          >
            <ListChecks size={16} />
            Sala de espera
          </button>

          <button
            onClick={() => fetchAppointments()}
            className="inline-flex items-center gap-2 neu-btn-secondary"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Atualizar
          </button>

          <button
            onClick={() => { setModalPrefill({}); setShowModal(true) }}
            className="inline-flex items-center gap-2 neu-btn-primary"
          >
            <Plus size={16} />
            Agendar
          </button>
        </div>
      </div>

      {(error || actionError) && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={16} />
          {error ?? actionError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <KpiTile
          tone="info"
          icon={<CalendarDays size={14} />}
          label="Hoje"
          value={todayAppointments.length}
          hint={`${checkedInToday} com chegada registrada`}
        />
        <KpiTile
          tone="attention"
          icon={<ListChecks size={14} />}
          label="Fila ativa"
          value={queueAppointments.length}
          hint={`${delayedToday} exigem atenção`}
        />
        <KpiTile
          tone="success"
          icon={<PlayCircle size={14} />}
          label="Em atendimento"
          value={inProgressToday}
          hint="consultas iniciadas"
        />
        <KpiTile
          icon={<CheckCircle2 size={14} />}
          label="Concluídos"
          value={completedToday}
          hint="atendimentos finalizados"
        />
        <KpiTile
          tone="critical"
          icon={<AlertTriangle size={14} />}
          label="Atritos"
          value={terminalFriction}
          hint="faltas ou cancelamentos"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="flex flex-col gap-2 border-b border-slate-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Fila assistencial de hoje</h2>
              <p className="mt-0.5 text-xs text-slate-500">Chegadas, atrasos e chamadas</p>
            </div>
            {lastUpdated && (
              <span className="text-xs text-slate-500">
                Atualizado {lastUpdated.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>

          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full min-w-[980px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  {['Horário', 'Paciente', 'Profissional', 'Tipo', 'Status', 'Sinal', 'Ações'].map((h) => (
                    <th key={h} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-4">
                      <ActionSkeleton />
                    </td>
                  </tr>
                ) : queueRows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center">
                      <CheckCircle2 size={34} className="mx-auto mb-3 text-slate-300" />
                      <p className="font-semibold text-slate-700">Nenhum paciente pendente na fila.</p>
                      <p className="mt-1 text-sm text-slate-500">A operação de hoje está sem chegada ou chamada pendente.</p>
                    </td>
                  </tr>
                ) : queueRows}
              </tbody>
            </table>
          </div>

          <div className="divide-y divide-slate-100 lg:hidden">
            {loading ? (
              <div className="p-4">
                <ActionSkeleton />
              </div>
            ) : queueAppointments.length === 0 ? (
              <div className="p-8 text-center">
                <CheckCircle2 size={34} className="mx-auto mb-3 text-slate-300" />
                <p className="font-semibold text-slate-700">Nenhum paciente pendente na fila.</p>
                <p className="mt-1 text-sm text-slate-500">A operação de hoje está sem pendências.</p>
              </div>
            ) : queueAppointments.map((appt) => {
              const meta = getAppointmentStatusMeta(appt.status)
              const tone = getQueueTone(appt, clientNow)
              const disabled = isUpdating(appt)
              const terminal = TERMINAL_STATUSES.has(appt.status)
              return (
                <div key={appt.id} className={`border-l-4 p-4 ${meta.borderClass} ${meta.rowClass}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <button
                        onClick={() => setDetailAppt(appt)}
                        className="block max-w-full truncate text-left font-semibold text-slate-900"
                      >
                        {appt.patient_name}
                      </button>
                      <p className="mt-1 text-xs text-slate-500">
                        {formatTimeRange(appt)} · {appt.professional_name}
                      </p>
                      <p className="mt-1 font-mono text-xs text-slate-500">{appt.patient_mrn}</p>
                    </div>
                    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}>
                      {appointmentBadgeLabel(appt.status, appt.status_display)}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{appt.type_display}</span>
                    <span className={`rounded-full border px-2 py-0.5 font-semibold ${TONE_CLASSES[tone]}`}>
                      {getQueueSignal(appt, clientNow)}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-2">
                    <button
                      disabled={disabled || Boolean(appt.arrived_at) || appt.status === 'in_progress' || terminal}
                      onClick={() => runAppointmentAction(appt, 'check-in')}
                      className="inline-flex items-center justify-center gap-1 rounded-lg bg-blue-100 px-2 py-2 text-xs font-semibold text-blue-700 disabled:opacity-40"
                    >
                      <UserCheck size={13} />
                      Registrar chegada
                    </button>
                    <button
                      disabled={disabled || terminal}
                      onClick={() => runAppointmentAction(appt, 'start')}
                      className="inline-flex items-center justify-center gap-1 rounded-lg bg-green-100 px-2 py-2 text-xs font-semibold text-green-700 disabled:opacity-40"
                      >
                        <PlayCircle size={13} />
                        {appt.status === 'in_progress' ? 'Abrir atendimento' : 'Iniciar atendimento'}
                      </button>
                    <button
                      disabled={disabled}
                      onClick={() => setPixAppt(appt)}
                      className="inline-flex items-center justify-center gap-1 rounded-lg bg-slate-100 px-2 py-2 block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide disabled:opacity-40"
                    >
                      <CircleDollarSign size={13} />
                      PIX
                    </button>
                    <button
                      disabled={disabled || terminal}
                      onClick={() => runAppointmentAction(appt, 'no_show')}
                      className="inline-flex items-center justify-center gap-1 rounded-lg bg-red-50 px-2 py-2 text-xs font-semibold text-red-600 disabled:opacity-40"
                    >
                      <XCircle size={13} />
                      Faltou
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <aside className="space-y-4">
          <section className="neu-panel">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Clock size={16} className="text-blue-600" />
              Próxima ação
            </div>
            {nextAction ? (
              <div className="mt-4 space-y-3">
                <div>
                  <p className="text-lg font-semibold text-slate-950">{nextAction.patient_name}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    {formatTimeRange(nextAction)} · {nextAction.professional_name}
                  </p>
                </div>
                <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE_CLASSES[getQueueTone(nextAction, clientNow)]}`}>
                  {getQueueSignal(nextAction, clientNow)}
                </span>
                <div className="grid grid-cols-1 gap-2">
                  <button
                    disabled={isUpdating(nextAction) || Boolean(nextAction.arrived_at) || nextAction.status === 'in_progress'}
                    onClick={() => runAppointmentAction(nextAction, 'check-in')}
                    className="inline-flex items-center justify-center gap-2    disabled:opacity-40 neu-btn-primary"
                  >
                    <UserCheck size={15} />
                    Registrar chegada
                  </button>
                  <button
                    disabled={isUpdating(nextAction) || TERMINAL_STATUSES.has(nextAction.status)}
                    onClick={() => runAppointmentAction(nextAction, 'start')}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-green-600 px-3 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-40"
                  >
                    <PlayCircle size={15} />
                    {nextAction.status === 'in_progress' ? 'Abrir atendimento' : 'Iniciar atendimento'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-5 rounded-lg border border-slate-100 bg-slate-50 px-3 py-4 text-sm text-slate-500">
                Nenhuma ação assistencial pendente.
              </div>
            )}
          </section>

          <section className="neu-panel">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <AlertTriangle size={16} className="text-red-600" />
              Atritos do dia
            </div>
            <div className="mt-4 space-y-2">
              {todayAppointments
                .filter((appt) => {
                  const lateMin = getLateMinutes(appt, clientNow)
                  const waitMin = getWaitMinutes(appt, clientNow)
                  return ['cancelled', 'no_show'].includes(appt.status)
                    || (lateMin != null && lateMin >= 10)
                    || (waitMin != null && waitMin >= 30)
                })
                .slice(0, 5)
                .map((appt) => (
                  <button
                    key={appt.id}
                    onClick={() => setDetailAppt(appt)}
                    className="w-full rounded-lg border border-slate-100 px-3 py-2 text-left hover:bg-slate-50"
                  >
                    <p className="truncate text-sm font-semibold text-slate-900">{appt.patient_name}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {formatTimeRange(appt)} · {getQueueSignal(appt, clientNow)}
                    </p>
                  </button>
                ))}
              {delayedToday === 0 && terminalFriction === 0 && (
                <div className="rounded-lg border border-green-100 bg-green-50 px-3 py-4 text-sm text-green-700">
                  Sem atraso crítico, falta ou cancelamento na operação de hoje.
                </div>
              )}
            </div>
          </section>
        </aside>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-col gap-3 border-b border-slate-100 px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2">
            <LayoutGrid size={16} className="text-slate-500" />
            <h2 className="text-base font-semibold text-slate-900">Grade semanal</h2>
          </div>
          <div className="hidden flex-wrap gap-2 text-xs sm:flex">
            {[
              { status: 'scheduled', label: 'Agendado' },
              { status: 'confirmed', label: 'Confirmado' },
              { status: 'waiting', label: 'Aguardando' },
              { status: 'in_progress', label: 'Em atendimento' },
              { status: 'completed', label: 'Concluído' },
              { status: 'cancelled', label: 'Cancelado' },
            ].map(({ status, label }) => (
              <span key={status} className={`rounded-full border px-2 py-0.5 text-xs ${getAppointmentStatusMeta(status).badgeClass}`}>
                {label}
              </span>
            ))}
          </div>
        </div>

        <div className="hidden max-h-[680px] overflow-auto md:block">
          {loading ? (
            <div className="flex h-64 items-center justify-center text-sm text-slate-400">
              Carregando agenda...
            </div>
          ) : (
            <table className="w-full min-w-[760px] border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-white">
                <tr>
                  <th className="w-14 border-b border-r border-slate-200 py-2 font-normal text-slate-400" />
                  {weekDates.map((d) => {
                    const isToday = clientNow ? isoDate(d) === isoDate(clientNow) : false
                    return (
                      <th
                        key={d.toISOString()}
                        className={`border-b border-r border-slate-200 py-2 font-medium ${
                          isToday ? 'bg-blue-50 text-blue-600' : 'text-slate-700'
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
                  <tr key={hour}>
                    <td className="w-14 border-b border-r border-slate-100 px-2 py-1 text-right font-mono text-slate-400">
                      {hour}
                    </td>
                    {weekDates.map((d) => {
                      const slotAppts = getApptForSlot(d, hour)
                      const isPast = clientNow ? new Date(`${isoDate(d)}T${hour}:00`) < clientNow : false
                      return (
                        <td
                          key={d.toISOString()}
                          className={`h-11 border-b border-r border-slate-100 p-0.5 align-top ${
                            isPast ? 'bg-slate-50/60' : 'cursor-pointer hover:bg-blue-50/60'
                          }`}
                          onClick={() => !isPast && slotAppts.length === 0 && handleSlotClick(d, hour)}
                        >
                          {slotAppts.map((appt) => (
                            <button
                              key={appt.id}
                              className={`w-full truncate rounded border px-1.5 py-1 text-left text-xs leading-tight ${
                                getAppointmentStatusMeta(appt.status).badgeClass
                              }`}
                              onClick={(e) => { e.stopPropagation(); setDetailAppt(appt) }}
                              title={`${appt.patient_name} - ${appt.type_display}`}
                            >
                              <div className="truncate font-medium">{appt.patient_name}</div>
                              <div className="truncate opacity-70">{appt.type_display}</div>
                              {(appt.whatsapp_confirmed || appt.whatsapp_reminder_sent) && (
                                <div className={`mt-0.5 inline-block rounded px-1 py-0 text-[9px] font-medium ${
                                  appt.whatsapp_confirmed
                                    ? 'bg-green-100 text-green-700'
                                    : 'bg-yellow-100 text-yellow-700'
                                }`}>
                                  {appt.whatsapp_confirmed ? 'WA ok' : 'WA enviado'}
                                </div>
                              )}
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

        <div className="divide-y divide-slate-100 md:hidden">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-slate-400">
              Carregando agenda...
            </div>
          ) : (() => {
            const todayStr = clientNow ? isoDate(clientNow) : isoDate(new Date())
            const dayStr = weekDates.find((d) => isoDate(d) === todayStr) ? todayStr : isoDate(weekDates[0])
            const dayAppts = appointments
              .filter((appt) => appt.start_time.split('T')[0] === dayStr)
              .sort((a, b) => a.start_time.localeCompare(b.start_time))
            const dayDate = new Date(`${dayStr}T00:00:00`)
            return (
              <>
                <div className="px-4 py-3 text-sm font-semibold capitalize text-slate-700">
                  {formatDayLong(dayDate)}
                </div>
                {dayAppts.length === 0 ? (
                  <div className="p-8 text-center text-sm text-slate-400">
                    Nenhuma consulta neste dia.
                  </div>
                ) : dayAppts.map((appt) => {
                  const meta = getAppointmentStatusMeta(appt.status)
                  return (
                    <div key={appt.id} className="flex items-start gap-3 px-4 py-3">
                      <div className="w-12 shrink-0 pt-0.5 font-mono text-xs text-slate-500">
                        {formatPtTime(appt.start_time)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-slate-900">{appt.patient_name}</p>
                        <p className="truncate text-xs text-slate-500">{appt.type_display} · {appt.professional_name}</p>
                        <span className={`mt-1 inline-block rounded-full border px-2 py-0.5 text-xs ${meta.badgeClass}`}>
                          {appointmentBadgeLabel(appt.status, appt.status_display)}
                        </span>
                      </div>
                      <button
                        onClick={() => setDetailAppt(appt)}
                        className="shrink-0 rounded-lg border border-blue-200 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50"
                      >
                        Ver
                      </button>
                    </div>
                  )
                })}
              </>
            )
          })()}
        </div>
      </section>

      {detailAppt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-slate-900">Detalhes do Agendamento</h2>
              <button
                onClick={() => setDetailAppt(null)}
                className="rounded-lg p-1 text-slate-400 hover:text-slate-700"
              >
                X
              </button>
            </div>
            <div className="space-y-4 px-6 py-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs text-slate-500">Paciente</p>
                  <p className="font-semibold text-slate-900">{detailAppt.patient_name}</p>
                  <p className="font-mono text-xs text-slate-400">{detailAppt.patient_mrn}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Profissional</p>
                  <p className="font-semibold text-slate-900">{detailAppt.professional_name}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Horário</p>
                  <p className="font-semibold text-slate-900">{formatTimeRange(detailAppt)}</p>
                  <p className="text-xs text-slate-400">{detailAppt.duration_minutes} min</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Tipo</p>
                  <p className="font-semibold text-slate-900">{detailAppt.type_display}</p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${getAppointmentStatusMeta(detailAppt.status).badgeClass}`}>
                  {appointmentBadgeLabel(detailAppt.status, detailAppt.status_display)}
                </span>
                <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${TONE_CLASSES[getQueueTone(detailAppt, clientNow)]}`}>
                  {getQueueSignal(detailAppt, clientNow)}
                </span>
              </div>

              {(detailAppt.whatsapp_confirmed || detailAppt.whatsapp_reminder_sent) && (
                <div>
                  <p className="mb-1 text-xs text-slate-500">WhatsApp</p>
                  <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${
                    detailAppt.whatsapp_confirmed
                      ? 'border-green-200 bg-green-50 text-green-700'
                      : 'border-yellow-200 bg-yellow-50 text-yellow-700'
                  }`}>
                    {detailAppt.whatsapp_confirmed ? 'Confirmado pelo paciente' : 'Lembrete enviado'}
                  </span>
                </div>
              )}

              {detailAppt.notes && (
                <div>
                  <p className="text-xs text-slate-500">Observações</p>
                  <p className="text-slate-700">{detailAppt.notes}</p>
                </div>
              )}

              <div className="border-t border-slate-100 pt-3">
                <button
                  onClick={() => { setPixAppt(detailAppt); setDetailAppt(null) }}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700"
                >
                  <CircleDollarSign size={16} />
                  Cobrar via PIX
                </button>
              </div>

              <div className="border-t border-slate-100 pt-3">
                <p className="mb-2 text-xs text-slate-500">Ações de status</p>
                <div className="flex flex-wrap gap-2">
                  {[
                    { value: 'confirmed' as const, label: 'Confirmar' },
                    { value: 'check-in' as const, label: 'Registrar chegada' },
                    { value: 'start' as const, label: 'Iniciar atendimento' },
                    { value: 'completed' as const, label: 'Concluir' },
                    { value: 'no_show' as const, label: 'Não compareceu' },
                    { value: 'cancelled' as const, label: 'Cancelar' },
                  ]
                    .filter((item) => {
                      if (item.value === 'check-in') return detailAppt.status !== 'waiting' && !detailAppt.arrived_at
                      if (item.value === 'start') return detailAppt.status !== 'in_progress'
                      return item.value !== detailAppt.status
                    })
                    .map((item) => (
                      <button
                        key={item.value}
                        disabled={isUpdating(detailAppt)}
                        onClick={() => runAppointmentAction(detailAppt, item.value)}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${
                          item.value === 'check-in'
                            ? getAppointmentStatusMeta('waiting').badgeClass
                            : item.value === 'start'
                            ? getAppointmentStatusMeta('in_progress').badgeClass
                            : getAppointmentStatusMeta(item.value).badgeClass
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

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

      {pixAppt && (
        <PIXModal
          appointmentId={pixAppt.id}
          amount={150}
          patientName={pixAppt.patient_name}
          onClose={() => setPixAppt(null)}
          onPaid={() => {
            setPixAppt(null)
            fetchAppointments()
          }}
        />
      )}
    </PageShell>
  )
}
