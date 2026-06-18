'use client'

import { useState, useEffect } from 'react'
import { trackPilotEvent } from '@/lib/analytics'

// ─── Types ────────────────────────────────────────────────────────────────────

interface WizardData {
  council_type: string
  council_number: string
  council_state: string
  specialty: string
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
    <div className="space-y-3">
      <div className="bg-[#E6F0F9] px-3 py-1.5 border-l-4 border-[#0066A1]">
        <h3 className="text-sm font-bold text-[#0066A1]">Informações do Corpo Clínico</h3>
      </div>
      <div className="grid grid-cols-12 gap-3 px-2">
        <div className="col-span-3">
          <label className="block text-xs font-semibold text-[#24292F] mb-1">Conselho *</label>
          <select
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] bg-white h-7"
            value={data.council_type}
            onChange={(e) => onChange({ council_type: e.target.value })}
          >
            {COUNCIL_TYPES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div className="col-span-6">
          <label className="block text-xs font-semibold text-[#24292F] mb-1">Número de Registro *</label>
          <input
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] h-7"
            placeholder="Ex: 123456"
            value={data.council_number}
            onChange={(e) => onChange({ council_number: e.target.value })}
          />
        </div>
        <div className="col-span-3">
          <label className="block text-xs font-semibold text-[#24292F] mb-1">UF *</label>
          <select
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] bg-white h-7"
            value={data.council_state}
            onChange={(e) => onChange({ council_state: e.target.value })}
          >
            {BR_STATES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
      </div>
      <div className="px-2 pb-2">
        <label className="block text-xs font-semibold text-[#24292F] mb-1">Especialidade Principal</label>
        <input
          className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] h-7"
          placeholder="Ex: Clínica Médica, Cardiologia"
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
    <div className="space-y-4">
      <div className="bg-[#E6F0F9] px-3 py-1.5 border-l-4 border-[#0066A1]">
        <h3 className="text-sm font-bold text-[#0066A1]">Configuração de Agenda e Turnos</h3>
      </div>
      
      <div className="px-2">
        <label className="block text-xs font-semibold text-[#24292F] mb-1">Dias de Atendimento</label>
        <div className="flex gap-1">
          {DAYS.map((d) => (
            <button
              key={d.value}
              type="button"
              onClick={() => toggleDay(d.value)}
              className={`px-3 py-1 text-xs border rounded-sm font-semibold transition-colors ${
                data.working_days.includes(d.value)
                  ? 'bg-[#0066A1] text-white border-[#004b7a]'
                  : 'bg-[#F4F6F8] text-[#57606A] border-[#D0D7DE] hover:bg-[#EAECEF]'
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 px-2">
        <div>
          <label className="block text-xs font-semibold text-[#24292F] mb-1">Início Expediente</label>
          <input
            type="time"
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] h-7"
            value={data.work_start}
            onChange={(e) => onChange({ work_start: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-[#24292F] mb-1">Início Pausa</label>
          <input
            type="time"
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] h-7"
            value={data.lunch_start}
            onChange={(e) => onChange({ lunch_start: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-[#24292F] mb-1">Fim Pausa</label>
          <input
            type="time"
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] h-7"
            value={data.lunch_end}
            onChange={(e) => onChange({ lunch_end: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-[#24292F] mb-1">Fim Expediente</label>
          <input
            type="time"
            className="w-full px-2 py-1 border border-[#D0D7DE] rounded-sm text-xs focus:outline-none focus:border-[#0066A1] h-7"
            value={data.work_end}
            onChange={(e) => onChange({ work_end: e.target.value })}
          />
        </div>
      </div>

      <div className="px-2 pb-2">
        <label className="block text-xs font-semibold text-[#24292F] mb-1">Duração Padrão do Encaixe (Slots)</label>
        <div className="flex gap-1">
          {SLOT_OPTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => onChange({ slot_duration_minutes: s })}
              className={`px-3 py-1 text-xs border rounded-sm font-semibold transition-colors ${
                data.slot_duration_minutes === s
                  ? 'bg-[#0066A1] text-white border-[#004b7a]'
                  : 'bg-[#F4F6F8] text-[#57606A] border-[#D0D7DE] hover:bg-[#EAECEF]'
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
    <div className="space-y-4 px-2 pb-2">
      <div className="bg-[#E6F0F9] px-3 py-1.5 border-l-4 border-[#0066A1] mb-4">
        <h3 className="text-sm font-bold text-[#0066A1]">Provisionamento Concluído</h3>
      </div>
      <p className="text-sm text-[#24292F] font-semibold">
        A parametrização inicial da clínica foi registrada com sucesso no banco de dados.
      </p>
      <div className="bg-[#F8FAFC] border border-[#D0D7DE] rounded-sm p-3 mt-2">
        <h4 className="text-xs font-bold text-[#57606A] uppercase mb-2">Próximas Ações Requeridas</h4>
        <ul className="text-xs text-[#24292F] space-y-1.5 list-disc list-inside">
          <li>Acessar o módulo de <strong>Agenda</strong> para cadastrar os primeiros horários.</li>
          <li>Iniciar o cadastro de <strong>Pacientes</strong> via módulo de Recepção.</li>
          <li>Revisar integrações no menu <strong>Configurações (F12)</strong>.</li>
        </ul>
      </div>
      <div className="pt-2">
        <a
          href="/dashboard"
          className="inline-block px-4 py-1.5 bg-[#0066A1] text-white text-xs font-bold rounded-sm border border-[#004b7a] hover:bg-[#004b7a]"
        >
          Acessar Workspace Principal
        </a>
      </div>
    </div>
  )
}

// ─── Wizard shell ─────────────────────────────────────────────────────────────

const STEPS = ['Parâmetros Profissionais', 'Regras de Agendamento', 'Confirmação']

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
      const r = await fetch('/api/v1/emr/setup/professional/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
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
      setError(e instanceof Error ? e.message : 'Erro ao salvar configuração do sistema.')
      trackPilotEvent('wizard_error', { error: e instanceof Error ? e.message : 'Unknown' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#E5E5E5] font-sans flex items-start justify-center pt-10 px-4">
      <div className="bg-white border border-[#B0B0B0] w-full max-w-3xl shadow-sm rounded-sm overflow-hidden flex flex-col">
        
        {/* Title Bar - Windows/Enterprise feel */}
        <div className="bg-[#0066A1] px-4 py-1.5 flex justify-between items-center border-b border-[#004b7a]">
          <span className="text-white text-sm font-bold tracking-wide">Vitali EMR - Setup Wizard</span>
          <span className="text-[#99C2E1] text-xs font-mono">v2.1.0</span>
        </div>

        <div className="flex flex-1">
          {/* Left Sidebar Steps */}
          <div className="w-56 bg-[#F4F6F8] border-r border-[#D0D7DE] shrink-0 hidden sm:block">
            <div className="p-3 border-b border-[#D0D7DE]">
              <span className="text-xs font-bold text-[#57606A] uppercase tracking-wider">Etapas de Setup</span>
            </div>
            <div className="py-2">
              {STEPS.map((label, i) => {
                const done = i < step
                const active = i === step
                return (
                  <div
                    key={i}
                    className={`px-4 py-2 text-xs font-semibold flex items-center gap-2 border-l-4 ${
                      active
                        ? 'border-[#0066A1] bg-white text-[#0066A1]'
                        : done
                        ? 'border-[#2DA44E] text-[#24292F]'
                        : 'border-transparent text-[#57606A]'
                    }`}
                  >
                    {done ? <span className="text-[#2DA44E] font-bold">✓</span> : <span className="w-2" />}
                    {label}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Main Content Area */}
          <div className="flex-1 flex flex-col bg-white">
            <div className="flex-1 p-4">
              {step === 0 && <StepProfessional data={data} onChange={update} />}
              {step === 1 && <StepSchedule data={data} onChange={update} />}
              {step === 2 && <StepComplete />}

              {error && (
                <div className="mt-4 px-3 py-2 bg-[#FFEBE9] border border-[#FF8182] text-[#CF222E] text-xs font-semibold rounded-sm">
                  Falha no sistema: {error}
                </div>
              )}
            </div>

            {/* Footer Action Bar */}
            {step < 2 && (
              <div className="bg-[#F8FAFC] border-t border-[#D0D7DE] px-4 py-2 flex justify-between items-center">
                <button
                  onClick={() => setStep((s) => Math.max(0, s - 1))}
                  disabled={step === 0}
                  className="px-4 py-1 text-xs font-semibold text-[#24292F] bg-[#F4F6F8] border border-[#D0D7DE] rounded-sm hover:bg-[#EAECEF] disabled:opacity-40"
                >
                  &larr; Voltar
                </button>
                <button
                  onClick={handleNext}
                  disabled={!canNext() || saving}
                  className="px-6 py-1 text-xs font-bold text-white bg-[#0066A1] border border-[#004b7a] rounded-sm hover:bg-[#004b7a] disabled:opacity-50 min-w-[100px]"
                >
                  {saving ? 'Processando...' : step === 1 ? 'Finalizar Setup' : 'Avançar \u2192'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
