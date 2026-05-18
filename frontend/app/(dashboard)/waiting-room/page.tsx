'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  Clock,
  PlayCircle,
  RefreshCw,
  UserCheck,
  XCircle,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { appointmentBadgeLabel, formatPtTime, getAppointmentStatusMeta } from '@/lib/operational-ui'
import { KpiTile, PageShell, StatusBadge } from '@/components/shared'

interface Appointment {
  id: string
  patient_name: string
  patient_mrn: string
  professional_name: string
  start_time: string
  end_time: string
  type_display: string
  status: string
  status_display: string
  duration_minutes: number
  arrived_at: string | null
}

function TableSkeleton() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i}>
          <td colSpan={8} className="px-4 py-3">
            <div className="h-4 w-4/5 animate-pulse rounded bg-slate-100" />
          </td>
        </tr>
      ))}
    </>
  )
}

function minutesSince(value?: string | null) {
  if (!value) return null
  return Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000))
}

export default function WaitingRoomPage() {
  const router = useRouter()
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [updating, setUpdating] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchWaiting = useCallback(async () => {
    try {
      setError(null)
      const d = await apiFetch<Appointment[]>('/api/v1/waiting-room/')
      setAppointments(Array.isArray(d) ? d : [])
      setLastUpdated(new Date())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível atualizar a sala de espera.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchWaiting()
    const interval = setInterval(fetchWaiting, 30_000)
    return () => clearInterval(interval)
  }, [fetchWaiting])

  const updateStatus = async (appt: Appointment, newStatus: string) => {
    setUpdating(appt.id)
    try {
      await apiFetch(`/api/v1/appointments/${appt.id}/status/`, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus }),
      })
      await fetchWaiting()
    } finally {
      setUpdating(null)
    }
  }

  const checkIn = async (appt: Appointment) => {
    setUpdating(appt.id)
    try {
      await apiFetch(`/api/v1/appointments/${appt.id}/check-in/`, {
        method: 'POST',
      })
      await fetchWaiting()
    } finally {
      setUpdating(null)
    }
  }

  const startAppointment = async (appt: Appointment) => {
    setUpdating(appt.id)
    try {
      const data = await apiFetch<{ encounter_id?: string }>(`/api/v1/appointments/${appt.id}/start/`, {
        method: 'POST',
      })
      if (data.encounter_id) {
        router.push(`/encounters/${data.encounter_id}`)
        return
      }
      await fetchWaiting()
    } finally {
      setUpdating(null)
    }
  }

  const [todayAll, setTodayAll] = useState<Appointment[]>([])
  useEffect(() => {
    apiFetch<Appointment[]>('/api/v1/appointments/today/')
      .then((d) => setTodayAll(Array.isArray(d) ? d : []))
      .catch(() => {})
  }, [lastUpdated])

  const waitingCount = appointments.filter((a) => ['scheduled', 'confirmed', 'waiting'].includes(a.status)).length
  const checkedInCount = appointments.filter((a) => a.arrived_at !== null || a.status === 'waiting').length
  const inProgressCount = todayAll.filter((a) => a.status === 'in_progress').length
  const completedCount = todayAll.filter((a) => a.status === 'completed').length

  const nextPatient = useMemo(
    () => appointments.slice().sort((a, b) => a.start_time.localeCompare(b.start_time))[0] ?? null,
    [appointments]
  )
  const longestWaitMin = useMemo(() => {
    const waits = appointments
      .map((appt) => minutesSince(appt.arrived_at ?? appt.start_time))
      .filter((value): value is number => value !== null)
    return waits.length ? Math.max(...waits) : null
  }, [appointments])

  const refresh = () => {
    setLoading(true)
    fetchWaiting()
  }

  return (
    <PageShell variant="operational">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Sala de Espera Operacional</h1>
          <p className="mt-1 text-sm text-slate-500">
            Fila de hoje com atualização automática.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => router.push('/appointments')}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <CalendarDays size={14} />
            Agenda
          </button>
          <button
            onClick={refresh}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Atualizar
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile
          tone="attention"
          icon={<Clock size={14} />}
          label="Aguardando"
          value={waitingCount}
          hint={`${checkedInCount} com chegada registrada`}
        />
        <KpiTile
          tone="success"
          icon={<UserCheck size={14} />}
          label="Em atendimento"
          value={inProgressCount}
          hint="consultas em execução"
        />
        <KpiTile
          icon={<CheckCircle2 size={14} />}
          label="Concluídos"
          value={completedCount}
          hint="finalizados hoje"
        />
        <KpiTile
          icon={<Clock size={14} />}
          label="Maior espera"
          value={longestWaitMin == null ? '—' : `${longestWaitMin} min`}
          hint={
            lastUpdated
              ? `Atualizado ${lastUpdated.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`
              : 'Atualização automática a cada 30s'
          }
        />
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {nextPatient && !loading && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Próximo paciente</p>
              <p className="mt-1 text-lg font-semibold text-blue-950">{nextPatient.patient_name}</p>
              <p className="text-sm text-blue-800">
                {formatPtTime(nextPatient.start_time)} · {nextPatient.professional_name} · {nextPatient.type_display}
              </p>
            </div>
            <button
              disabled={updating === nextPatient.id}
              onClick={() => startAppointment(nextPatient)}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <PlayCircle size={16} />
              Chamar agora
            </button>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="hidden overflow-x-auto lg:block">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Horário', 'Paciente', 'Prontuário', 'Profissional', 'Tipo', 'Espera', 'Status', 'Ações'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {loading ? (
                <TableSkeleton />
              ) : appointments.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-14 text-center">
                    <CheckCircle2 size={36} className="mx-auto mb-3 text-slate-300" />
                    <p className="font-medium text-slate-700">Nenhum paciente aguardando</p>
                    <p className="mt-1 text-sm text-slate-500">
                      Todos os agendamentos de hoje foram atendidos ou estão em andamento.
                    </p>
                  </td>
                </tr>
              ) : appointments.map((appt) => {
                const meta = getAppointmentStatusMeta(appt.status)
                const waitMin = minutesSince(appt.arrived_at ?? appt.start_time)
                return (
                  <tr key={appt.id} className={`border-l-4 ${meta.borderClass} ${meta.rowClass} hover:bg-blue-50`}>
                    <td className="px-4 py-3 font-mono text-slate-700">{formatPtTime(appt.start_time)}</td>
                    <td className="px-4 py-3 font-medium text-slate-900">{appt.patient_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">{appt.patient_mrn}</td>
                    <td className="px-4 py-3 text-slate-600">{appt.professional_name}</td>
                    <td className="px-4 py-3 text-slate-500">{appt.type_display}</td>
                    <td className="px-4 py-3 text-slate-700">{waitMin == null ? '—' : `${waitMin} min`}</td>
                    <td className="px-4 py-3">
                      <StatusBadge meta={meta} label={appointmentBadgeLabel(appt.status, appt.status_display)} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <button
                          disabled={updating === appt.id || appt.arrived_at !== null}
                          onClick={() => checkIn(appt)}
                          className="inline-flex items-center gap-1 rounded-lg bg-blue-100 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-200 disabled:opacity-50"
                          title={appt.arrived_at ? 'Paciente já registrou chegada' : 'Registrar chegada do paciente'}
                        >
                          <UserCheck size={12} />
                          Chegou
                        </button>
                        {appt.status !== 'in_progress' ? (
                          <button
                            disabled={updating === appt.id}
                            onClick={() => startAppointment(appt)}
                            className="inline-flex items-center gap-1 rounded-lg bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700 hover:bg-green-200 disabled:opacity-50"
                            title="Chamar paciente"
                          >
                            <PlayCircle size={12} />
                            Chamar
                          </button>
                        ) : (
                          <button
                            disabled={updating === appt.id}
                            onClick={() => updateStatus(appt, 'completed')}
                            className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-200 disabled:opacity-50"
                            title="Concluir atendimento"
                          >
                            <CheckCircle2 size={12} />
                            Concluir
                          </button>
                        )}
                        <button
                          disabled={updating === appt.id}
                          onClick={() => updateStatus(appt, 'no_show')}
                          className="inline-flex items-center gap-1 rounded-lg bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-600 hover:bg-red-100 disabled:opacity-50"
                          title="Marcar como não compareceu"
                        >
                          <XCircle size={12} />
                          Faltou
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="divide-y divide-slate-100 lg:hidden">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="p-4">
                <div className="h-4 w-3/4 animate-pulse rounded bg-slate-100" />
                <div className="mt-2 h-3 w-1/2 animate-pulse rounded bg-slate-100" />
              </div>
            ))
          ) : appointments.length === 0 ? (
            <div className="p-8 text-center">
              <CheckCircle2 size={36} className="mx-auto mb-3 text-slate-300" />
              <p className="font-medium text-slate-700">Nenhum paciente aguardando</p>
              <p className="mt-1 text-sm text-slate-500">A operação de hoje está sem fila pendente.</p>
            </div>
          ) : appointments.map((appt) => {
            const meta = getAppointmentStatusMeta(appt.status)
            const waitMin = minutesSince(appt.arrived_at ?? appt.start_time)
            return (
              <div key={appt.id} className={`border-l-4 p-4 ${meta.borderClass} ${meta.rowClass}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-slate-900">{appt.patient_name}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatPtTime(appt.start_time)} · {appt.professional_name}
                    </p>
                    <p className="mt-1 font-mono text-xs text-slate-500">{appt.patient_mrn}</p>
                  </div>
                  <StatusBadge meta={meta} label={appointmentBadgeLabel(appt.status, appt.status_display)} className="shrink-0" />
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
                  <span>{appt.type_display}</span>
                  <span>·</span>
                  <span>{waitMin == null ? 'Espera não registrada' : `${waitMin} min de espera`}</span>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2">
                  <button
                    disabled={updating === appt.id || appt.arrived_at !== null}
                    onClick={() => checkIn(appt)}
                    className="rounded-lg bg-blue-100 px-2 py-2 text-xs font-semibold text-blue-700 disabled:opacity-50"
                  >
                    Chegou
                  </button>
                  <button
                    disabled={updating === appt.id}
                    onClick={() => appt.status === 'in_progress' ? updateStatus(appt, 'completed') : startAppointment(appt)}
                    className="rounded-lg bg-green-100 px-2 py-2 text-xs font-semibold text-green-700 disabled:opacity-50"
                  >
                    {appt.status === 'in_progress' ? 'Concluir' : 'Chamar'}
                  </button>
                  <button
                    disabled={updating === appt.id}
                    onClick={() => updateStatus(appt, 'no_show')}
                    className="rounded-lg bg-red-50 px-2 py-2 text-xs font-semibold text-red-600 disabled:opacity-50"
                  >
                    Faltou
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </PageShell>
  )
}
