'use client'

import { useState, useEffect } from 'react'
import { CheckCircle, ChevronRight, ChevronLeft, User, Clock, Rocket } from 'lucide-react'
import { trackPilotEvent } from '@/lib/analytics'

// ─── Types ────────────────────────────────────────────────────────────────────

interface WizardData {
  // Step 1: Professional
  council_type: string
  council_number: string
  council_state: string
  specialty: string
  // Step 2: Schedule
  working_days: number[]
  work_start: string
  work_end: string
  lunch_start: string
  lunch_end: string
  slot_duration_minutes: number
}

const INITIAL: WizardData = {
  council_type: 'CRM',
  council_number: '',
  council_state: 'SP',
  specialty: '',
  working_days: [1, 2, 3, 4, 5],
  work_start: '08:00',
  work_end: '18:00',
  lunch_start: '12:00',
  lunch_end: '13:00',
  slot_duration_minutes: 30,
}

const COUNCIL_TYPES = ['CRM', 'CRO', 'CRN', 'CREF', 'CRP', 'CFO', 'COREN']
const BR_STATES = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO']
const DAYS = [
  { label: 'Dom', value: 0 },
  { label: 'Seg', value: 1 },
  { label: 'Ter', value: 2 },
  { label: 'Qua', value: 3 },
  { label: 'Qui', value: 4 },
  { label: 'Sex', value: 5 },
  { label: 'Sáb', value: 6 },
]
const SLOT_OPTIONS = [15, 20, 30, 45, 60]

// ─── Step components ──────────────────────────────────────────────────────────

function StepProfessional({ data, onChange }: { data: WizardData; onChange: (d: Partial<WizardData>) => void }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Conselho *</label>
          <select
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={data.council_type}
            onChange={(e) => onChange({ council_type: e.target.value })}
          >
            {COUNCIL_TYPES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Número *</label>
          <input
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="123456"
            value={data.council_number}
            onChange={(e) => onChange({ council_number: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">UF *</label>
          <select
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={data.council_state}
            onChange={(e) => onChange({ council_state: e.target.value })}
          >
            {BR_STATES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">Especialidade</label>
        <input
          className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Clínica Geral, Cardiologia..."
          value={data.specialty}
          onChange={(e) => onChange({ specialty: e.target.value })}
        />
      </div>
    </div>
  )
}

function StepSchedule({ data, onChange }: { data: WizardData; onChange: (d: Partial<WizardData>) => void }) {
  const toggleDay = (day: number) => {
    const current = data.working_days
    const next = current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort()
    onChange({ working_days: next })
  }

  return (
    <div className="space-y-5">
      <div>
        <label className="block text-sm font-medium text-slate-700 mb-2">Dias de atendimento</label>
        <div className="flex gap-2 flex-wrap">
          {DAYS.map((d) => (
            <button
              key={d.value}
              type="button"
              onClick={() => toggleDay(d.value)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                data.working_days.includes(d.value)
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300'
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-400 mt-1">Clique para ativar/desativar</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Início do expediente</label>
          <input
            type="time"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={data.work_start}
            onChange={(e) => onChange({ work_start: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Fim do expediente</label>
          <input
            type="time"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={data.work_end}
            onChange={(e) => onChange({ work_end: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Início do almoço</label>
          <input
            type="time"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={data.lunch_start}
            onChange={(e) => onChange({ lunch_start: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Fim do almoço</label>
          <input
            type="time"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={data.lunch_end}
            onChange={(e) => onChange({ lunch_end: e.target.value })}
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-2">Duração dos slots</label>
        <div className="flex gap-2 flex-wrap">
          {SLOT_OPTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange({ slot_duration_minutes: s })}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                data.slot_duration_minutes === s
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300'
              }`}
            >
              {s} min
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function StepComplete() {
  return (
    <div className="text-center space-y-5 py-4">
      <div className="mx-auto w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
        <CheckCircle size={32} className="text-green-600" />
      </div>
      <div>
        <h3 className="text-xl font-semibold text-slate-900">
          Tudo pronto!
        </h3>
        <p className="text-slate-500 mt-2 text-sm">
          A configuração inicial foi concluída. Você pode editar qualquer informação em Configurações a qualquer momento.
        </p>
      </div>
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-sm text-slate-600 text-left space-y-2">
        <p className="font-medium text-slate-700">Próximos passos</p>
        <ul className="space-y-1 list-disc list-inside">
          <li>Agende sua primeira consulta na <strong>Agenda</strong></li>
          <li>Cadastre pacientes em <strong>Pacientes</strong></li>
          <li>Configure o WhatsApp em <strong>Configurações → WhatsApp</strong></li>
          <li>Leia o <a href="/docs/USER_GUIDE.md" className="text-blue-600 hover:underline">Guia do Usuário</a></li>
        </ul>
      </div>
      <a
        href="/dashboard"
        className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700"
      >
        <Rocket size={16} />
        Ir para o Painel
      </a>
    </div>
  )
}

// ─── Wizard shell ─────────────────────────────────────────────────────────────

const STEPS = [
  { icon: User, label: 'Profissional' },
  { icon: Clock, label: 'Agenda' },
  { icon: CheckCircle, label: 'Concluído' },
]

export default function SetupWizardPage() {
  const [step, setStep] = useState(0)
  const [data, setData] = useState<WizardData>(INITIAL)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    trackPilotEvent('wizard_started')
  }, [])

  const update = (patch: Partial<WizardData>) => setData((d) => ({ ...d, ...patch }))

  const canNext = () => {
    if (step === 0) return data.council_number.trim().length > 0
    return true
  }

  const handleNext = async () => {
    if (step === 1) {
      // Step 2 → submit to backend
      await submit()
    } else {
      setStep((s) => s + 1)
      trackPilotEvent('wizard_step_completed', { step })
    }
  }

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      const payload = {
        council_type: data.council_type,
        council_number: data.council_number,
        council_state: data.council_state,
        specialty: data.specialty,
        working_days: data.working_days,
        work_start: data.work_start,
        work_end: data.work_end,
        lunch_start: data.lunch_start,
        lunch_end: data.lunch_end,
        slot_duration_minutes: data.slot_duration_minutes,
      }
      const r = await fetch('/api/v1/emr/setup/professional/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(JSON.stringify(body))
      }
      
      trackPilotEvent('wizard_completed', { 
        council_type: data.council_type,
        working_days_count: data.working_days.length,
        slot_duration: data.slot_duration_minutes 
      })
      
      setStep(2)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erro ao salvar configurações.')
      trackPilotEvent('wizard_error', { error: e instanceof Error ? e.message : 'Unknown' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-blue-600 to-indigo-600 px-8 py-6 text-white">
          <p className="text-xs font-medium opacity-70 uppercase tracking-wide">Vitali</p>
          <h1 className="text-xl font-semibold mt-1">Configuração Inicial</h1>
        </div>

        {/* Step indicators */}
        <div className="flex border-b border-slate-100">
          {STEPS.map((s, i) => {
            const Icon = s.icon
            const done = i < step
            const active = i === step
            return (
              <div
                key={i}
                className={`flex-1 flex flex-col items-center py-3 gap-1 text-center ${
                  active
                    ? 'border-b-2 border-blue-600'
                    : done
                    ? 'text-green-600'
                    : 'text-slate-300'
                }`}
              >
                <Icon size={16} className={active ? 'text-blue-600' : done ? 'text-green-500' : 'text-slate-300'} />
                <span className={`text-[10px] font-medium hidden sm:block ${active ? 'text-blue-600' : done ? 'text-green-600' : 'text-slate-400'}`}>
                  {s.label}
                </span>
              </div>
            )
          })}
        </div>

        {/* Step content */}
        <div className="px-8 py-6">
          {step === 0 && <StepProfessional data={data} onChange={update} />}
          {step === 1 && <StepSchedule data={data} onChange={update} />}
          {step === 2 && <StepComplete />}

          {error && (
            <p className="mt-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </div>

        {/* Navigation */}
        {step < 2 && (
          <div className="px-8 pb-6 flex items-center justify-between">
            <button
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
              className="flex items-center gap-1 px-4 py-2 text-sm text-slate-500 hover:text-slate-700 disabled:opacity-30"
            >
              <ChevronLeft size={16} />
              Voltar
            </button>
            <button
              onClick={handleNext}
              disabled={!canNext() || saving}
              className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white text-sm font-semibold rounded-xl hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Salvando...' : step === 1 ? 'Concluir' : 'Próximo'}
              {!saving && <ChevronRight size={16} />}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

