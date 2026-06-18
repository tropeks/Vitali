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

// ─── Shared UI Components ─────────────────────────────────────────────────────

const inputClasses = "w-full px-2 py-1.5 bg-[#E8EDF2] border-transparent rounded-md text-xs shadow-[inset_0_2px_4px_rgba(0,0,0,0.06)] focus:outline-none focus:bg-white focus:ring-2 focus:ring-[#0066A1]/50 transition-all h-8 text-[#24292F]"
const labelClasses = "block text-[11px] font-bold text-[#57606A] mb-1.5 uppercase tracking-wide"

// ─── Step components ──────────────────────────────────────────────────────────

function StepProfessional({ data, onChange }: { data: WizardData; onChange: (d: Partial<WizardData>) => void }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-1.5 h-4 bg-[#0066A1] rounded-full shadow-[0_0_6px_rgba(0,102,161,0.4)]"></div>
        <h3 className="text-sm font-bold text-[#1f2937]">Informações do Corpo Clínico</h3>
      </div>
      
      <div className="bg-[#F4F7FA] p-4 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] space-y-4 border border-white">
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-3">
            <label className={labelClasses}>Conselho *</label>
            <select
              className={inputClasses}
              value={data.council_type}
              onChange={(e) => onChange({ council_type: e.target.value })}
            >
              {COUNCIL_TYPES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="col-span-6">
            <label className={labelClasses}>Número de Registro *</label>
            <input
              className={inputClasses}
              placeholder="Ex: 123456"
              value={data.council_number}
              onChange={(e) => onChange({ council_number: e.target.value })}
            />
          </div>
          <div className="col-span-3">
            <label className={labelClasses}>UF *</label>
            <select
              className={inputClasses}
              value={data.council_state}
              onChange={(e) => onChange({ council_state: e.target.value })}
            >
              {BR_STATES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className={labelClasses}>Especialidade Principal</label>
          <input
            className={inputClasses}
            placeholder="Ex: Clínica Médica, Cardiologia"
            value={data.specialty}
            onChange={(e) => onChange({ specialty: e.target.value })}
          />
        </div>
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
      <div className="flex items-center gap-2 mb-4">
        <div className="w-1.5 h-4 bg-[#0066A1] rounded-full shadow-[0_0_6px_rgba(0,102,161,0.4)]"></div>
        <h3 className="text-sm font-bold text-[#1f2937]">Configuração de Agenda e Turnos</h3>
      </div>
      
      <div className="bg-[#F4F7FA] p-4 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] space-y-5 border border-white">
        <div>
          <label className={labelClasses}>Dias de Atendimento</label>
          <div className="flex gap-2 flex-wrap">
            {DAYS.map((d) => (
              <button
                key={d.value}
                type="button"
                onClick={() => toggleDay(d.value)}
                className={`px-4 py-1.5 text-xs rounded-lg font-bold transition-all ${
                  data.working_days.includes(d.value)
                    ? 'bg-gradient-to-b from-[#0066A1] to-[#005282] text-white shadow-[0_2px_6px_rgba(0,102,161,0.3)] border-t border-[#3385b5]'
                    : 'bg-[#E8EDF2] text-[#57606A] shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),_0_2px_4px_rgba(0,0,0,0.05)] hover:bg-[#dfe5ea]'
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-4 gap-4">
          <div>
            <label className={labelClasses}>Início Expediente</label>
            <input
              type="time"
              className={inputClasses}
              value={data.work_start}
              onChange={(e) => onChange({ work_start: e.target.value })}
            />
          </div>
          <div>
            <label className={labelClasses}>Início Pausa</label>
            <input
              type="time"
              className={inputClasses}
              value={data.lunch_start}
              onChange={(e) => onChange({ lunch_start: e.target.value })}
            />
          </div>
          <div>
            <label className={labelClasses}>Fim Pausa</label>
            <input
              type="time"
              className={inputClasses}
              value={data.lunch_end}
              onChange={(e) => onChange({ lunch_end: e.target.value })}
            />
          </div>
          <div>
            <label className={labelClasses}>Fim Expediente</label>
            <input
              type="time"
              className={inputClasses}
              value={data.work_end}
              onChange={(e) => onChange({ work_end: e.target.value })}
            />
          </div>
        </div>

        <div>
          <label className={labelClasses}>Duração Padrão do Encaixe (Slots)</label>
          <div className="flex gap-2 flex-wrap">
            {SLOT_OPTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onChange({ slot_duration_minutes: s })}
                className={`px-4 py-1.5 text-xs rounded-lg font-bold transition-all ${
                  data.slot_duration_minutes === s
                    ? 'bg-gradient-to-b from-[#0066A1] to-[#005282] text-white shadow-[0_2px_6px_rgba(0,102,161,0.3)] border-t border-[#3385b5]'
                    : 'bg-[#E8EDF2] text-[#57606A] shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),_0_2px_4px_rgba(0,0,0,0.05)] hover:bg-[#dfe5ea]'
                }`}
              >
                {s} min
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function StepComplete() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-1.5 h-4 bg-[#2DA44E] rounded-full shadow-[0_0_6px_rgba(45,164,78,0.4)]"></div>
        <h3 className="text-sm font-bold text-[#1f2937]">Provisionamento Concluído</h3>
      </div>
      
      <div className="bg-[#F4F7FA] p-5 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] border border-white">
        <p className="text-sm text-[#24292F] font-semibold mb-4">
          A parametrização inicial da clínica foi registrada com sucesso no banco de dados corporativo.
        </p>
        
        <div className="bg-[#E8EDF2] rounded-lg p-4 shadow-[inset_0_2px_4px_rgba(0,0,0,0.04)]">
          <h4 className="text-xs font-bold text-[#57606A] uppercase tracking-wide mb-3">Próximas Ações Requeridas</h4>
          <ul className="text-xs text-[#24292F] space-y-2 list-disc list-inside">
            <li>Acessar o módulo de <strong>Agenda</strong> para cadastrar os primeiros horários.</li>
            <li>Iniciar o cadastro de <strong>Pacientes</strong> via módulo de Recepção.</li>
            <li>Revisar integrações no menu <strong>Configurações (F12)</strong>.</li>
          </ul>
        </div>
      </div>
      
      <div className="pt-2 text-right">
        <a
          href="/dashboard"
          className="inline-block px-6 py-2 bg-gradient-to-b from-[#2DA44E] to-[#248f42] text-white text-xs font-bold rounded-lg border-t border-[#4ac26c] shadow-[0_3px_8px_rgba(45,164,78,0.3)] hover:shadow-[0_4px_12px_rgba(45,164,78,0.4)] transition-all"
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
    <div className="min-h-screen bg-[#DFE5EB] font-sans flex items-center justify-center p-4">
      
      {/* Neumorphic Main Container */}
      <div className="bg-[#EBF0F5] w-full max-w-4xl rounded-2xl shadow-[0_10px_30px_rgba(0,0,0,0.1),_inset_0_2px_4px_rgba(255,255,255,0.8)] overflow-hidden flex flex-col border border-white/50">
        
        {/* Header - Soft Corporate Blue */}
        <div className="bg-[#EBF0F5] px-6 py-4 flex justify-between items-center border-b border-[#D0D7DE]/50 shadow-[0_2px_10px_rgba(0,0,0,0.02)] z-10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#0066A1] to-[#004b7a] shadow-[0_2px_8px_rgba(0,102,161,0.4)] flex items-center justify-center text-white font-bold text-xs">
              V
            </div>
            <div>
              <h1 className="text-[#1f2937] text-sm font-bold tracking-wide">Vitali EMR Solutions</h1>
              <h2 className="text-[#57606A] text-[10px] font-semibold uppercase tracking-wider">Setup Initialization</h2>
            </div>
          </div>
          <span className="px-2 py-1 bg-[#E8EDF2] text-[#57606A] rounded-md text-[10px] font-bold shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)]">v2.1.0</span>
        </div>

        <div className="flex flex-1 min-h-[400px]">
          {/* Left Sidebar Steps - Neumorphic raised pills */}
          <div className="w-64 bg-[#EBF0F5] p-6 shrink-0 hidden sm:block border-r border-[#D0D7DE]/40">
            <div className="space-y-3">
              {STEPS.map((label, i) => {
                const done = i < step
                const active = i === step
                return (
                  <div
                    key={i}
                    className={`px-4 py-3 rounded-xl text-xs font-bold flex items-center gap-3 transition-all ${
                      active
                        ? 'bg-[#F4F7FA] text-[#0066A1] shadow-[inset_0_2px_4px_rgba(255,255,255,0.8),_0_4px_10px_rgba(0,0,0,0.04)] border border-white'
                        : done
                        ? 'text-[#57606A] opacity-70'
                        : 'text-[#8C959F] opacity-50'
                    }`}
                  >
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] ${
                      active ? 'bg-[#0066A1] text-white shadow-[0_2px_6px_rgba(0,102,161,0.3)]' : 
                      done ? 'bg-[#2DA44E] text-white' : 'bg-[#D0D7DE] text-white'
                    }`}>
                      {done ? '✓' : i + 1}
                    </div>
                    {label}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Main Content Area */}
          <div className="flex-1 flex flex-col bg-[#F8FAFC] shadow-[inset_4px_0_12px_rgba(0,0,0,0.02)]">
            <div className="flex-1 p-8">
              {step === 0 && <StepProfessional data={data} onChange={update} />}
              {step === 1 && <StepSchedule data={data} onChange={update} />}
              {step === 2 && <StepComplete />}

              {error && (
                <div className="mt-6 px-4 py-3 bg-[#FFEBE9] border border-[#FF8182]/50 shadow-[inset_0_2px_4px_rgba(255,255,255,0.5),_0_2px_8px_rgba(207,34,46,0.1)] text-[#CF222E] text-xs font-bold rounded-xl">
                  Falha de Sistema: {error}
                </div>
              )}
            </div>

            {/* Footer Action Bar - Neumorphic elevated */}
            {step < 2 && (
              <div className="bg-[#F4F7FA] border-t border-white px-8 py-5 flex justify-between items-center shadow-[0_-4px_15px_rgba(0,0,0,0.02)] z-10">
                <button
                  onClick={() => setStep((s) => Math.max(0, s - 1))}
                  disabled={step === 0}
                  className="px-5 py-2 text-xs font-bold text-[#57606A] bg-[#E8EDF2] rounded-lg shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),_0_2px_5px_rgba(0,0,0,0.05)] hover:bg-[#dfe5ea] disabled:opacity-40 transition-all"
                >
                  Voltar
                </button>
                <button
                  onClick={handleNext}
                  disabled={!canNext() || saving}
                  className="px-8 py-2 text-xs font-bold text-white bg-gradient-to-b from-[#0066A1] to-[#005282] rounded-lg border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] disabled:opacity-50 transition-all min-w-[120px]"
                >
                  {saving ? 'Processando...' : step === 1 ? 'Finalizar Setup' : 'Avançar'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
