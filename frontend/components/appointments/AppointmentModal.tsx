'use client'

import { useState, useEffect, useCallback } from 'react'
import { X, Search } from 'lucide-react'

interface Patient {
  id: string
  full_name: string
  medical_record_number: string
}

interface Professional {
  id: string
  user_name: string
  specialty: string
}

interface Slot {
  start: string
  end: string
  available: boolean
}

interface Props {
  onClose: () => void
  onCreated: () => void
  prefillProfessionalId?: string
  prefillDate?: string
  prefillSlotStart?: string
  prefillSlotEnd?: string
}

const APPOINTMENT_TYPES = [
  { value: 'consultation', label: 'Consulta' },
  { value: 'return', label: 'Retorno' },
  { value: 'exam', label: 'Exame' },
  { value: 'procedure', label: 'Procedimento' },
  { value: 'telemedicine', label: 'Telemedicina' },
]

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>
  return ((...args: any[]) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }) as T
}

export default function AppointmentModal({
  onClose,
  onCreated,
  prefillProfessionalId,
  prefillDate,
  prefillSlotStart,
  prefillSlotEnd,
}: Props) {
  const [patientSearch, setPatientSearch] = useState('')
  const [patientResults, setPatientResults] = useState<Patient[]>([])
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const [professionals, setProfessionals] = useState<Professional[]>([])
  const [selectedProfId, setSelectedProfId] = useState(prefillProfessionalId ?? '')
  const [date, setDate] = useState(prefillDate ?? new Date().toISOString().split('T')[0])
  const [slots, setSlots] = useState<Slot[]>([])
  const [selectedSlot, setSelectedSlot] = useState<Slot | null>(
    prefillSlotStart && prefillSlotEnd
      ? { start: prefillSlotStart, end: prefillSlotEnd, available: true }
      : null,
  )
  const [type, setType] = useState('consultation')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [slotsLoading, setSlotsLoading] = useState(false)
  const [error, setError] = useState('')
  const [waitlistLoading, setWaitlistLoading] = useState(false)
  const [waitlistDone, setWaitlistDone] = useState(false)

  // Load professionals on mount
  useEffect(() => {
    fetch('/api/v1/professionals?ordering=user__full_name')
      .then((r) => r.json())
      .then((d) => setProfessionals(d.results ?? d))
      .catch(() => {})
  }, [])

  // Load slots when professional + date change
  useEffect(() => {
    if (!selectedProfId || !date) { setSlots([]); return }
    setSlotsLoading(true)
    fetch(`/api/v1/professionals/${selectedProfId}/available-slots?date=${date}&duration=30`)
      .then((r) => r.json())
      .then((d) => setSlots(d.slots ?? []))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false))
  }, [selectedProfId, date])

  // Patient autocomplete
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const searchPatients = useCallback(
    debounce(async (q: string) => {
      if (!q.trim()) { setPatientResults([]); return }
      const r = await fetch(`/api/v1/patients?search=${encodeURIComponent(q)}&ordering=full_name`)
      const d = await r.json()
      setPatientResults(d.results ?? [])
    }, 300),
    [],
  )

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedPatient || !selectedProfId || !selectedSlot) {
      setError('Preencha paciente, profissional e horário.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/v1/appointments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient: selectedPatient.id,
          professional: selectedProfId,
          start_time: selectedSlot.start,
          end_time: selectedSlot.end,
          type,
          notes,
          source: 'receptionist',
        }),
      })
      if (res.status === 409 || res.status === 400) {
        const data = await res.json()
        const msg =
          data?.start_time?.[0] ??
          data?.error?.message ??
          'Horário indisponível. Escolha outro slot.'
        const isConflict = res.status === 409 || msg.includes('TIME_SLOT_UNAVAILABLE')
        setError(isConflict ? 'Horário já ocupado. Escolha outro ou entre na fila de espera.' : msg)
        return
      }
      if (!res.ok) {
        setError('Erro ao criar agendamento.')
        return
      }
      onCreated()
    } finally {
      setLoading(false)
    }
  }

  const joinWaitlist = async () => {
    if (!selectedPatient || !selectedProfId || !date) {
      setError('Preencha paciente, profissional e data para entrar na fila.')
      return
    }
    setWaitlistLoading(true)
    setError('')
    try {
      const res = await fetch('/api/v1/waitlist/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          patient: selectedPatient.id,
          professional: selectedProfId || undefined,
          preferred_date_from: date,
          preferred_date_to: date,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.error?.message ?? data.detail ?? 'Erro ao entrar na lista de espera.')
        return
      }
      setWaitlistDone(true)
    } catch {
      setError('Erro ao entrar na lista de espera.')
    } finally {
      setWaitlistLoading(false)
    }
  }

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h2 className="text-lg font-semibold text-slate-900">Novo Agendamento</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 rounded-lg p-1">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Patient search */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Paciente</label>
            {selectedPatient ? (
              <div className="flex items-center justify-between px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg text-sm">
                <span className="font-medium text-blue-900">{selectedPatient.full_name}</span>
                <span className="text-blue-500 text-xs mr-2">{selectedPatient.medical_record_number}</span>
                <button
                  type="button"
                  onClick={() => { setSelectedPatient(null); setPatientResults([]) }}
                  className="text-blue-400 hover:text-blue-700"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="Buscar por nome ou prontuário..."
                  className="w-full pl-8 pr-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={patientSearch}
                  onChange={(e) => {
                    setPatientSearch(e.target.value)
                    searchPatients(e.target.value)
                  }}
                />
                {patientResults.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                    {patientResults.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 flex items-center justify-between"
                        onClick={() => {
                          setSelectedPatient(p)
                          setPatientSearch('')
                          setPatientResults([])
                        }}
                      >
                        <span className="font-medium text-slate-900">{p.full_name}</span>
                        <span className="text-slate-400 text-xs">{p.medical_record_number}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Professional */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Profissional</label>
            <select
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={selectedProfId}
              onChange={(e) => { setSelectedProfId(e.target.value); setSelectedSlot(null) }}
            >
              <option value="">Selecione...</option>
              {professionals.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.user_name}{p.specialty ? ` — ${p.specialty}` : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Date */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Data</label>
            <input
              type="date"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={date}
              onChange={(e) => { setDate(e.target.value); setSelectedSlot(null) }}
              min={new Date().toISOString().split('T')[0]}
            />
          </div>

          {/* Available slots */}
          {selectedProfId && date && (
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Horário</label>
              {slotsLoading ? (
                <div className="text-sm text-slate-400">Carregando horários...</div>
              ) : slots.length === 0 ? (
                <div className="space-y-2">
                  <div className="text-sm text-slate-400">Sem horários disponíveis para esta data.</div>
                  {waitlistDone ? (
                    <div className="px-3 py-2 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700 font-medium">
                      ✓ Adicionado à lista de espera.
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={joinWaitlist}
                      disabled={waitlistLoading || !selectedPatient}
                      className="text-sm text-blue-600 hover:text-blue-800 font-medium disabled:opacity-40 flex items-center gap-1"
                    >
                      {waitlistLoading ? 'Entrando na fila...' : '+ Entrar na fila de espera'}
                    </button>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-4 gap-1.5 max-h-36 overflow-y-auto pr-1">
                  {slots.map((slot) => {
                    const isSelected =
                      selectedSlot?.start === slot.start && selectedSlot?.end === slot.end
                    return (
                      <button
                        key={slot.start}
                        type="button"
                        disabled={!slot.available}
                        onClick={() => setSelectedSlot(slot)}
                        className={`px-2 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                          !slot.available
                            ? 'bg-slate-100 text-slate-300 cursor-not-allowed'
                            : isSelected
                            ? 'bg-blue-600 text-white'
                            : 'bg-blue-50 text-blue-700 hover:bg-blue-100'
                        }`}
                      >
                        {formatTime(slot.start)}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* Type */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Tipo</label>
            <select
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              {APPOINTMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Observações</label>
            <textarea
              rows={2}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder="Observações opcionais..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {error && (
            <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 space-y-1">
              <p>{error}</p>
              {error.includes('fila de espera') && !waitlistDone && (
                <button
                  type="button"
                  onClick={joinWaitlist}
                  disabled={waitlistLoading}
                  className="text-blue-600 hover:text-blue-800 font-medium text-xs underline disabled:opacity-40"
                >
                  {waitlistLoading ? 'Entrando na fila...' : 'Entrar na fila de espera →'}
                </button>
              )}
              {waitlistDone && (
                <p className="text-green-700 font-medium">✓ Adicionado à lista de espera.</p>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-slate-200 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? 'Agendando...' : 'Confirmar Agendamento'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
