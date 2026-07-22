'use client'

import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import PatientAutocomplete, { type PatientOption } from '@/components/patients/PatientAutocomplete'
import RemoteCombobox from '@/components/shared/RemoteCombobox'

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

export default function AppointmentModal({
  onClose,
  onCreated,
  prefillProfessionalId,
  prefillDate,
  prefillSlotStart,
  prefillSlotEnd,
}: Props) {
  const [selectedPatient, setSelectedPatient] = useState<PatientOption | null>(null)
  const [selectedProfessional, setSelectedProfessional] = useState<Professional | null>(null)
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

  // Resolve a calendar-prefilled professional without loading the whole directory.
  useEffect(() => {
    if (!prefillProfessionalId) return
    apiFetch<Professional>(`/api/v1/professionals/${prefillProfessionalId}/`)
      .then(setSelectedProfessional)
      .catch(() => {})
  }, [prefillProfessionalId])

  // Load slots when professional + date change
  useEffect(() => {
    if (!selectedProfId || !date) { setSlots([]); return }
    setSlotsLoading(true)
    apiFetch(`/api/v1/professionals/${selectedProfId}/available-slots/?date=${date}&duration=30`)
      .then((d) => setSlots(d.slots ?? []))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false))
  }, [selectedProfId, date])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedPatient || !selectedProfId || !selectedSlot) {
      setError('Preencha paciente, profissional e horário.')
      return
    }
    setLoading(true)
    setError('')
    try {
      await apiFetch('/api/v1/appointments/', {
        method: 'POST',
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
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && (err.status === 409 || err.status === 400)) {
        const data = err.body
        const msg =
          data?.start_time?.[0] ??
          data?.error?.message ??
          'Horário indisponível. Escolha outro slot.'
        const isConflict = err.status === 409 || msg.includes('TIME_SLOT_UNAVAILABLE')
        setError(isConflict ? 'Horário já ocupado. Escolha outro ou entre na fila de espera.' : msg)
        return
      }
      setError('Erro ao criar agendamento.')
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
      await apiFetch('/api/v1/waitlist/', {
        method: 'POST',
        body: JSON.stringify({
          patient_id: selectedPatient.id,
          professional_id: selectedProfId,
          preferred_date_from: date,
          preferred_date_to: date,
        }),
      })
      setWaitlistDone(true)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.body?.error?.message ?? err.body?.detail ?? 'Erro ao entrar na lista de espera.')
      } else {
        setError('Erro ao entrar na lista de espera.')
      }
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
          <PatientAutocomplete value={selectedPatient} onChange={setSelectedPatient} required />

          {/* Professional */}
          <div>
            <label className="block block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide mb-1">Profissional</label>
            <RemoteCombobox<Professional>
              label="Profissional"
              endpoint="/api/v1/professionals/?ordering=user__full_name"
              value={selectedProfessional}
              getKey={(professional) => professional.id}
              getLabel={(professional) => `${professional.user_name}${professional.specialty ? ` — ${professional.specialty}` : ''}`}
              onChange={(professional) => {
                setSelectedProfessional(professional)
                setSelectedProfId(professional?.id ?? '')
                setSelectedSlot(null)
              }}
              placeholder="Buscar por nome, conselho ou especialidade..."
            />
          </div>

          {/* Date */}
          <div>
            <label className="block block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide mb-1">Data</label>
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
              <label className="block block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide mb-1">Horário</label>
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
            <label className="block block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide mb-1">Tipo</label>
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
            <label className="block block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide mb-1">Observações</label>
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
