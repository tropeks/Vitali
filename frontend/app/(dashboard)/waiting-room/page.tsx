'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Clock, UserCheck, CheckCircle2, XCircle } from 'lucide-react'

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

const STATUS_COLORS: Record<string, string> = {
  scheduled: 'bg-slate-100 text-slate-700',
  confirmed: 'bg-blue-100 text-blue-700',
  waiting: 'bg-yellow-100 text-yellow-700',
  in_progress: 'bg-green-100 text-green-700',
  completed: 'bg-slate-100 text-slate-400',
  cancelled: 'bg-red-100 text-red-600',
  no_show: 'bg-red-100 text-red-600',
}

export default function WaitingRoomPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [updating, setUpdating] = useState<string | null>(null)

  const fetchWaiting = useCallback(async () => {
    try {
      const r = await fetch('/api/v1/waiting-room')
      const d = await r.json()
      setAppointments(Array.isArray(d) ? d : [])
      setLastUpdated(new Date())
    } catch {
      // silently keep last state on error
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
      const r = await fetch(`/api/v1/appointments/${appt.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (r.ok) await fetchWaiting()
    } finally {
      setUpdating(null)
    }
  }

  const checkIn = async (appt: Appointment) => {
    setUpdating(appt.id)
    try {
      const r = await fetch(`/api/v1/appointments/${appt.id}/check-in/`, {
        method: 'POST',
      })
      if (r.ok) await fetchWaiting()
    } finally {
      setUpdating(null)
    }
  }

  // Counters
  const waitingCount = appointments.filter((a) => ['scheduled', 'confirmed', 'waiting'].includes(a.status)).length

  // Fetch all of today for the counter totals (waiting-room only returns pending)
  const [todayAll, setTodayAll] = useState<Appointment[]>([])
  useEffect(() => {
    fetch('/api/v1/appointments/today')
      .then((r) => r.json())
      .then((d) => setTodayAll(Array.isArray(d) ? d : []))
      .catch(() => {})
  }, [lastUpdated])

  const inProgressCount = todayAll.filter((a) => a.status === 'in_progress').length
  const completedCount = todayAll.filter((a) => a.status === 'completed').length

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Sala de Espera</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            {lastUpdated
              ? `Atualizado às ${lastUpdated.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })} · atualiza automaticamente a cada 30s`
              : 'Atualiza automaticamente a cada 30s'}
          </p>
        </div>
        <button
          onClick={() => { setLoading(true); fetchWaiting() }}
          className="flex items-center gap-2 px-3 py-2 border border-slate-200 text-slate-600 rounded-lg text-sm hover:bg-slate-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Atualizar
        </button>
      </div>

      {/* Counters */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-5 py-4 flex items-center gap-4">
          <Clock className="text-yellow-500 shrink-0" size={24} />
          <div>
            <div className="text-2xl font-bold text-yellow-700">{waitingCount}</div>
            <div className="text-sm text-yellow-600">Aguardando</div>
          </div>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-xl px-5 py-4 flex items-center gap-4">
          <UserCheck className="text-green-500 shrink-0" size={24} />
          <div>
            <div className="text-2xl font-bold text-green-700">{inProgressCount}</div>
            <div className="text-sm text-green-600">Em atendimento</div>
          </div>
        </div>
        <div className="bg-slate-50 border border-slate-200 rounded-xl px-5 py-4 flex items-center gap-4">
          <CheckCircle2 className="text-slate-400 shrink-0" size={24} />
          <div>
            <div className="text-2xl font-bold text-slate-600">{completedCount}</div>
            <div className="text-sm text-slate-500">Concluídos</div>
          </div>
        </div>
      </div>

      {/* Patient list */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-400 text-sm">Carregando...</div>
        ) : appointments.length === 0 ? (
          <div className="p-12 text-center">
            <CheckCircle2 size={40} className="text-slate-200 mx-auto mb-3" />
            <p className="text-slate-500 font-medium">Nenhum paciente aguardando</p>
            <p className="text-slate-400 text-sm mt-1">Todos os agendamentos de hoje foram atendidos ou estão em andamento.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Horário', 'Paciente', 'Prontuário', 'Profissional', 'Tipo', 'Status', 'Ações'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-slate-600 text-xs">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {appointments.map((appt) => (
                <tr key={appt.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-mono text-slate-700">
                    {formatTime(appt.start_time)}
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900">{appt.patient_name}</td>
                  <td className="px-4 py-3 text-slate-500 font-mono text-xs">{appt.patient_mrn}</td>
                  <td className="px-4 py-3 text-slate-600">{appt.professional_name}</td>
                  <td className="px-4 py-3 text-slate-500">{appt.type_display}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[appt.status]}`}>
                      {appt.status_display}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <button
                        disabled={updating === appt.id || appt.arrived_at !== null}
                        onClick={() => checkIn(appt)}
                        className="flex items-center gap-1 px-2.5 py-1 bg-blue-100 text-blue-700 text-xs rounded-lg hover:bg-blue-200 disabled:opacity-50 font-medium"
                        title={appt.arrived_at ? 'Paciente já registrou chegada' : 'Registrar chegada do paciente'}
                      >
                        <UserCheck size={12} />
                        Chegou
                      </button>
                      {appt.status !== 'in_progress' && (
                        <button
                          disabled={updating === appt.id}
                          onClick={() => updateStatus(appt, 'in_progress')}
                          className="flex items-center gap-1 px-2.5 py-1 bg-green-100 text-green-700 text-xs rounded-lg hover:bg-green-200 disabled:opacity-50 font-medium"
                          title="Chamar paciente"
                        >
                          <UserCheck size={12} />
                          Chamar
                        </button>
                      )}
                      {appt.status === 'in_progress' && (
                        <button
                          disabled={updating === appt.id}
                          onClick={() => updateStatus(appt, 'completed')}
                          className="flex items-center gap-1 px-2.5 py-1 bg-slate-100 text-slate-600 text-xs rounded-lg hover:bg-slate-200 disabled:opacity-50 font-medium"
                          title="Concluir atendimento"
                        >
                          <CheckCircle2 size={12} />
                          Concluir
                        </button>
                      )}
                      <button
                        disabled={updating === appt.id}
                        onClick={() => updateStatus(appt, 'no_show')}
                        className="flex items-center gap-1 px-2.5 py-1 bg-red-50 text-red-500 text-xs rounded-lg hover:bg-red-100 disabled:opacity-50 font-medium"
                        title="Marcar como não compareceu"
                      >
                        <XCircle size={12} />
                        Faltou
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
