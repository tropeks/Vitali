'use client'

import { useState, useEffect, useCallback } from 'react'
import { trackPilotEvent } from '@/lib/analytics'
import { apiFetch, ApiError } from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ClinicData {
  razao_social: string
  cnpj: string
  address: string
  dpo_name: string
  dpo_email: string
  dpo_phone: string
}

interface ProfessionalData {
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

interface PlanData {
  name: string
  ans_code: string
}

interface DpaStatus {
  is_signed: boolean
  signed_at: string | null
  signed_by_name: string | null
  current_user_can_sign: boolean
}

const CLINIC_INITIAL: ClinicData = {
  razao_social: '',
  cnpj: '',
  address: '',
  dpo_name: '',
  dpo_email: '',
  dpo_phone: '',
}

const PROFESSIONAL_INITIAL: ProfessionalData = {
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

const PLAN_INITIAL: PlanData = { name: '', ans_code: '' }

const COUNCIL_TYPES = ['CRM', 'CRO', 'CRN', 'CREF', 'CRP', 'CFO', 'COREN', 'CRF', 'CREFITO']
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

// Friendly catalog for the module-review step. Keys mirror FeatureFlag.module_key.
const MODULE_CATALOG: { key: string; label: string; description: string }[] = [
  { key: 'emr', label: 'Prontuário Eletrônico (EMR)', description: 'Pacientes, agenda e atendimentos' },
  { key: 'billing', label: 'Faturamento TISS/TUSS', description: 'Guias, convênios e glosas' },
  { key: 'pharmacy', label: 'Farmácia e Estoque', description: 'Dispensação e controle de estoque' },
  { key: 'whatsapp', label: 'WhatsApp', description: 'Confirmações e lembretes automáticos' },
  { key: 'ai_tuss', label: 'IA — Sugestão TUSS', description: 'Sugestão automática de códigos' },
  { key: 'ai_scribe', label: 'IA — Escriba Clínico', description: 'Transcrição e nota assistida (exige DPA)' },
]

// ─── Step indices ─────────────────────────────────────────────────────────────

const STEP_CLINIC = 0
const STEP_PROFESSIONAL = 1
const STEP_SCHEDULE = 2
const STEP_PLAN = 3
const STEP_MODULES = 4
const STEP_DPA = 5
const STEP_DONE = 6

const STEPS = [
  'Dados da Clínica',
  'Corpo Clínico',
  'Regras de Agendamento',
  'Plano de Saúde',
  'Módulos Ativos',
  'Termo de Tratamento (DPA)',
  'Conclusão',
]

// ─── Shared UI ────────────────────────────────────────────────────────────────

const inputClasses = "w-full px-2 py-1.5 bg-[#E8EDF2] border-transparent rounded-md text-xs shadow-[inset_0_2px_4px_rgba(0,0,0,0.06)] focus:outline-none focus:bg-white focus:ring-2 focus:ring-[#0066A1]/50 transition-all h-8 text-[#24292F]"
const labelClasses = "block text-[11px] font-bold text-[#57606A] mb-1.5 uppercase tracking-wide"

function StepHeader({ title, accent = '#0066A1' }: { title: string; accent?: string }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <div className="w-1.5 h-4 rounded-full" style={{ backgroundColor: accent, boxShadow: `0 0 6px ${accent}66` }}></div>
      <h3 className="text-sm font-bold text-[#1f2937]">{title}</h3>
    </div>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-[#F4F7FA] p-4 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] space-y-4 border border-white">
      {children}
    </div>
  )
}

function extractError(e: unknown): string {
  if (e instanceof ApiError) {
    const b = e.body
    if (b && typeof b === 'object') {
      if (b.error?.message) return b.error.message as string
      if (b.error?.details) return JSON.stringify(b.error.details)
      if (b.detail) return b.detail as string
      return JSON.stringify(b)
    }
    return `Erro ${e.status}`
  }
  return e instanceof Error ? e.message : 'Erro inesperado ao salvar.'
}

// ─── Step 1: Clinic data ──────────────────────────────────────────────────────

function StepClinic({ data, onChange }: { data: ClinicData; onChange: (d: Partial<ClinicData>) => void }) {
  return (
    <div className="space-y-4">
      <StepHeader title="Identificação da Clínica" />
      <p className="text-[11px] text-[#57606A] -mt-2">
        Estes dados aparecem em guias, receituários e no registro LGPD da clínica.
      </p>

      <Card>
        <div>
          <label className={labelClasses}>Razão Social *</label>
          <input
            className={inputClasses}
            placeholder="Ex: Clínica Vitali Saúde LTDA"
            value={data.razao_social}
            onChange={(e) => onChange({ razao_social: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-5">
            <label className={labelClasses}>CNPJ *</label>
            <input
              className={inputClasses}
              placeholder="00.000.000/0001-00"
              value={data.cnpj}
              onChange={(e) => onChange({ cnpj: e.target.value })}
            />
          </div>
          <div className="col-span-7">
            <label className={labelClasses}>Endereço</label>
            <input
              className={inputClasses}
              placeholder="Rua, número, bairro, cidade/UF"
              value={data.address}
              onChange={(e) => onChange({ address: e.target.value })}
            />
          </div>
        </div>
      </Card>

      <StepHeader title="Encarregado de Dados (DPO) — LGPD" />
      <Card>
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-5">
            <label className={labelClasses}>Nome do Encarregado</label>
            <input
              className={inputClasses}
              placeholder="Responsável pela proteção de dados"
              value={data.dpo_name}
              onChange={(e) => onChange({ dpo_name: e.target.value })}
            />
          </div>
          <div className="col-span-4">
            <label className={labelClasses}>E-mail do DPO</label>
            <input
              className={inputClasses}
              type="email"
              placeholder="dpo@clinica.com.br"
              value={data.dpo_email}
              onChange={(e) => onChange({ dpo_email: e.target.value })}
            />
          </div>
          <div className="col-span-3">
            <label className={labelClasses}>Telefone</label>
            <input
              className={inputClasses}
              placeholder="(11) 90000-0000"
              value={data.dpo_phone}
              onChange={(e) => onChange({ dpo_phone: e.target.value })}
            />
          </div>
        </div>
      </Card>
    </div>
  )
}

// ─── Step 2: Professional ─────────────────────────────────────────────────────

function StepProfessional({ data, onChange }: { data: ProfessionalData; onChange: (d: Partial<ProfessionalData>) => void }) {
  return (
    <div className="space-y-4">
      <StepHeader title="Informações do Corpo Clínico" />
      <Card>
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-3">
            <label className={labelClasses}>Conselho *</label>
            <select className={inputClasses} value={data.council_type} onChange={(e) => onChange({ council_type: e.target.value })}>
              {COUNCIL_TYPES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="col-span-6">
            <label className={labelClasses}>Número de Registro *</label>
            <input className={inputClasses} placeholder="Ex: 123456" value={data.council_number} onChange={(e) => onChange({ council_number: e.target.value })} />
          </div>
          <div className="col-span-3">
            <label className={labelClasses}>UF *</label>
            <select className={inputClasses} value={data.council_state} onChange={(e) => onChange({ council_state: e.target.value })}>
              {BR_STATES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className={labelClasses}>Especialidade Principal</label>
          <input className={inputClasses} placeholder="Ex: Clínica Médica, Cardiologia" value={data.specialty} onChange={(e) => onChange({ specialty: e.target.value })} />
        </div>
      </Card>
    </div>
  )
}

// ─── Step 3: Schedule ─────────────────────────────────────────────────────────

function StepSchedule({ data, onChange }: { data: ProfessionalData; onChange: (d: Partial<ProfessionalData>) => void }) {
  const toggleDay = (day: number) => {
    const current = data.working_days
    const next = current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort()
    onChange({ working_days: next })
  }

  return (
    <div className="space-y-4">
      <StepHeader title="Configuração de Agenda e Turnos" />
      <Card>
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
            <input type="time" className={inputClasses} value={data.work_start} onChange={(e) => onChange({ work_start: e.target.value })} />
          </div>
          <div>
            <label className={labelClasses}>Início Pausa</label>
            <input type="time" className={inputClasses} value={data.lunch_start} onChange={(e) => onChange({ lunch_start: e.target.value })} />
          </div>
          <div>
            <label className={labelClasses}>Fim Pausa</label>
            <input type="time" className={inputClasses} value={data.lunch_end} onChange={(e) => onChange({ lunch_end: e.target.value })} />
          </div>
          <div>
            <label className={labelClasses}>Fim Expediente</label>
            <input type="time" className={inputClasses} value={data.work_end} onChange={(e) => onChange({ work_end: e.target.value })} />
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
      </Card>
    </div>
  )
}

// ─── Step 4: First health plan ────────────────────────────────────────────────

function StepPlan({ data, onChange, onSkip }: { data: PlanData; onChange: (d: Partial<PlanData>) => void; onSkip: () => void }) {
  return (
    <div className="space-y-4">
      <StepHeader title="Primeiro Plano de Saúde (Convênio)" />
      <p className="text-[11px] text-[#57606A] -mt-2">
        Cadastre o convênio mais usado para já emitir guias. <strong>Opcional</strong> — você pode adicionar outros depois em Faturamento.
      </p>
      <Card>
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-7">
            <label className={labelClasses}>Nome da Operadora</label>
            <input className={inputClasses} placeholder="Ex: Unimed, Bradesco Saúde" value={data.name} onChange={(e) => onChange({ name: e.target.value })} />
          </div>
          <div className="col-span-5">
            <label className={labelClasses}>Código ANS</label>
            <input className={inputClasses} placeholder="Ex: 326305" value={data.ans_code} onChange={(e) => onChange({ ans_code: e.target.value })} />
          </div>
        </div>
        <div className="pt-1">
          <button
            type="button"
            onClick={onSkip}
            className="text-[11px] font-bold text-[#0066A1] hover:underline"
          >
            Pular esta etapa →
          </button>
        </div>
      </Card>
    </div>
  )
}

// ─── Step 5: Module review ────────────────────────────────────────────────────

function StepModules({ active, loading }: { active: string[] | null; loading: boolean }) {
  const extras = (active ?? []).filter((k) => !MODULE_CATALOG.some((m) => m.key === k))
  return (
    <div className="space-y-4">
      <StepHeader title="Revisão de Módulos Ativos" />
      <p className="text-[11px] text-[#57606A] -mt-2">
        Estes são os módulos liberados no seu plano. Para ativar outros, fale com o suporte comercial.
      </p>
      <Card>
        {loading ? (
          <p className="text-xs text-[#57606A]">Carregando módulos...</p>
        ) : (
          <div className="space-y-2">
            {MODULE_CATALOG.map((m) => {
              const on = (active ?? []).includes(m.key)
              return (
                <div key={m.key} className="flex items-center justify-between bg-[#E8EDF2] rounded-lg px-3 py-2 shadow-[inset_0_2px_4px_rgba(0,0,0,0.04)]">
                  <div>
                    <div className="text-xs font-bold text-[#24292F]">{m.label}</div>
                    <div className="text-[10px] text-[#57606A]">{m.description}</div>
                  </div>
                  <span className={`px-2 py-1 rounded-md text-[10px] font-bold ${
                    on
                      ? 'bg-gradient-to-b from-[#2DA44E] to-[#248f42] text-white shadow-[0_2px_6px_rgba(45,164,78,0.3)]'
                      : 'bg-[#D0D7DE] text-[#57606A]'
                  }`}>
                    {on ? 'ATIVO' : 'Inativo'}
                  </span>
                </div>
              )
            })}
            {extras.map((k) => (
              <div key={k} className="flex items-center justify-between bg-[#E8EDF2] rounded-lg px-3 py-2 shadow-[inset_0_2px_4px_rgba(0,0,0,0.04)]">
                <div className="text-xs font-bold text-[#24292F]">{k}</div>
                <span className="px-2 py-1 rounded-md text-[10px] font-bold bg-gradient-to-b from-[#2DA44E] to-[#248f42] text-white">ATIVO</span>
              </div>
            ))}
            {(active ?? []).length === 0 && (
              <p className="text-xs text-[#57606A]">Nenhum módulo ativo ainda. O EMR básico é liberado automaticamente após o setup.</p>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

// ─── Step 6: DPA confirmation ─────────────────────────────────────────────────

function StepDpa({ status, loading }: { status: DpaStatus | null; loading: boolean }) {
  return (
    <div className="space-y-4">
      <StepHeader title="Termo de Tratamento de Dados (DPA)" accent="#9A6700" />
      <p className="text-[11px] text-[#57606A] -mt-2">
        Exigido pela LGPD (Art. 11) antes de habilitar recursos de IA sobre dados de saúde.
      </p>
      <Card>
        {loading ? (
          <p className="text-xs text-[#57606A]">Verificando status do DPA...</p>
        ) : status?.is_signed ? (
          <div className="bg-[#E6F4EA] rounded-lg px-4 py-3 shadow-[inset_0_2px_4px_rgba(0,0,0,0.03)]">
            <p className="text-xs font-bold text-[#1A7F37]">✓ DPA já assinado</p>
            <p className="text-[11px] text-[#57606A] mt-1">
              Assinado por {status.signed_by_name ?? 'administrador'}{status.signed_at ? ` em ${status.signed_at}` : ''}.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-[#24292F]">
              Ao confirmar, você declara que a clínica possui acordo de tratamento de dados (DPA)
              válido com os provedores de IA, conforme a LGPD. Recursos de IA permanecem
              desativados até esta confirmação.
            </p>
            {!status?.current_user_can_sign && (
              <div className="bg-[#FFF8C5] rounded-lg px-3 py-2 text-[11px] text-[#7D4E00] font-semibold shadow-[inset_0_2px_4px_rgba(0,0,0,0.03)]">
                Seu usuário não tem permissão para assinar o DPA. Um administrador precisa concluir esta etapa.
                Você pode prosseguir e assinar depois em Configurações.
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

// ─── Step 7: Complete ─────────────────────────────────────────────────────────

function StepComplete() {
  return (
    <div className="space-y-4">
      <StepHeader title="Provisionamento Concluído" accent="#2DA44E" />
      <div className="bg-[#F4F7FA] p-5 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] border border-white">
        <p className="text-sm text-[#24292F] font-semibold mb-4">
          A clínica está pronta para receber o primeiro paciente. Toda a parametrização inicial
          foi registrada com sucesso.
        </p>
        <div className="bg-[#E8EDF2] rounded-lg p-4 shadow-[inset_0_2px_4px_rgba(0,0,0,0.04)]">
          <h4 className="text-xs font-bold text-[#57606A] uppercase tracking-wide mb-3">Próximas Ações</h4>
          <ul className="text-xs text-[#24292F] space-y-2 list-disc list-inside">
            <li>Cadastrar o <strong>primeiro paciente</strong> no módulo de Recepção.</li>
            <li>Agendar a <strong>primeira consulta</strong> na Agenda.</li>
            <li>Revisar convênios e integrações em <strong>Configurações</strong>.</li>
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

export default function SetupWizardPage() {
  const [step, setStep] = useState(0)
  const [clinic, setClinic] = useState<ClinicData>(CLINIC_INITIAL)
  const [professional, setProfessional] = useState<ProfessionalData>(PROFESSIONAL_INITIAL)
  const [plan, setPlan] = useState<PlanData>(PLAN_INITIAL)
  const [modules, setModules] = useState<string[] | null>(null)
  const [modulesLoading, setModulesLoading] = useState(false)
  const [dpa, setDpa] = useState<DpaStatus | null>(null)
  const [dpaLoading, setDpaLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    trackPilotEvent('wizard_started')
  }, [])

  const updateClinic = (patch: Partial<ClinicData>) => setClinic((d) => ({ ...d, ...patch }))
  const updateProfessional = (patch: Partial<ProfessionalData>) => setProfessional((d) => ({ ...d, ...patch }))
  const updatePlan = (patch: Partial<PlanData>) => setPlan((d) => ({ ...d, ...patch }))

  // Lazy-load module list when entering the review step.
  const loadModules = useCallback(async () => {
    setModulesLoading(true)
    try {
      const r = await apiFetch<{ active_modules: string[] }>('/api/v1/features/')
      setModules(r.active_modules ?? [])
    } catch {
      setModules([])
    } finally {
      setModulesLoading(false)
    }
  }, [])

  const loadDpa = useCallback(async () => {
    setDpaLoading(true)
    try {
      const r = await apiFetch<DpaStatus>('/api/v1/settings/dpa/')
      setDpa(r)
    } catch {
      setDpa(null)
    } finally {
      setDpaLoading(false)
    }
  }, [])

  useEffect(() => {
    if (step === STEP_MODULES && modules === null && !modulesLoading) loadModules()
    if (step === STEP_DPA && dpa === null && !dpaLoading) loadDpa()
  }, [step, modules, modulesLoading, dpa, dpaLoading, loadModules, loadDpa])

  const canNext = () => {
    if (saving) return false
    if (step === STEP_CLINIC) return clinic.razao_social.trim().length > 0 && clinic.cnpj.trim().length > 0
    if (step === STEP_PROFESSIONAL) return professional.council_number.trim().length > 0
    return true
  }

  // ── Per-step API wiring ──

  const submitClinic = async () => {
    await apiFetch('/api/v1/settings/clinic/', {
      method: 'PATCH',
      body: JSON.stringify({
        razao_social: clinic.razao_social,
        cnpj: clinic.cnpj,
        address: clinic.address,
        dpo_name: clinic.dpo_name,
        dpo_email: clinic.dpo_email,
        dpo_phone: clinic.dpo_phone,
      }),
    })
  }

  const submitProfessional = async () => {
    await apiFetch('/api/v1/emr/setup/professional/', {
      method: 'POST',
      body: JSON.stringify(professional),
    })
    trackPilotEvent('wizard_professional_saved', {
      council_type: professional.council_type,
      working_days_count: professional.working_days.length,
      slot_duration: professional.slot_duration_minutes,
    })
  }

  const submitPlan = async () => {
    // Optional step: only POST when the admin actually filled it in.
    if (!plan.name.trim() || !plan.ans_code.trim()) return
    await apiFetch('/api/v1/billing/providers/', {
      method: 'POST',
      body: JSON.stringify({ name: plan.name, ans_code: plan.ans_code }),
    })
    trackPilotEvent('wizard_plan_created')
  }

  const confirmDpa = async () => {
    // Sign only when needed and allowed; otherwise simply advance.
    if (dpa && !dpa.is_signed && dpa.current_user_can_sign) {
      const r = await apiFetch<DpaStatus>('/api/v1/settings/dpa/sign/', { method: 'POST' })
      setDpa(r)
      trackPilotEvent('wizard_dpa_signed')
    }
  }

  const advance = () => {
    trackPilotEvent('wizard_step_completed', { step })
    setStep((s) => s + 1)
  }

  const goToPlanSkip = () => {
    setPlan(PLAN_INITIAL)
    setError(null)
    setStep(STEP_MODULES)
    trackPilotEvent('wizard_step_completed', { step: STEP_PLAN, skipped: true })
  }

  const handleNext = async () => {
    setError(null)
    setSaving(true)
    try {
      if (step === STEP_CLINIC) await submitClinic()
      else if (step === STEP_SCHEDULE) await submitProfessional()
      else if (step === STEP_PLAN) await submitPlan()
      else if (step === STEP_DPA) await confirmDpa()

      if (step === STEP_DPA) {
        trackPilotEvent('wizard_completed')
      }
      advance()
    } catch (e: unknown) {
      const msg = extractError(e)
      setError(msg)
      trackPilotEvent('wizard_error', { step, error: msg })
    } finally {
      setSaving(false)
    }
  }

  const nextLabel = () => {
    if (saving) return 'Processando...'
    if (step === STEP_DPA) return dpa && !dpa.is_signed && dpa.current_user_can_sign ? 'Confirmar e Concluir' : 'Concluir'
    return 'Avançar'
  }

  return (
    <div className="min-h-screen bg-[#DFE5EB] font-sans flex items-center justify-center p-4">
      <div className="bg-[#EBF0F5] w-full max-w-4xl rounded-2xl shadow-[0_10px_30px_rgba(0,0,0,0.1),_inset_0_2px_4px_rgba(255,255,255,0.8)] overflow-hidden flex flex-col border border-white/50">

        {/* Header */}
        <div className="bg-[#EBF0F5] px-6 py-4 flex justify-between items-center border-b border-[#D0D7DE]/50 shadow-[0_2px_10px_rgba(0,0,0,0.02)] z-10">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#0066A1] to-[#004b7a] shadow-[0_2px_8px_rgba(0,102,161,0.4)] flex items-center justify-center text-white font-bold text-xs">
              V
            </div>
            <div>
              <h1 className="text-[#1f2937] text-sm font-bold tracking-wide">Vitali EMR Solutions</h1>
              <h2 className="text-[#57606A] text-[10px] font-semibold uppercase tracking-wider">Onboarding da Clínica</h2>
            </div>
          </div>
          <span className="px-2 py-1 bg-[#E8EDF2] text-[#57606A] rounded-md text-[10px] font-bold shadow-[inset_0_1px_2px_rgba(0,0,0,0.05)]">
            Etapa {Math.min(step + 1, STEPS.length)} de {STEPS.length}
          </span>
        </div>

        <div className="flex flex-1 min-h-[440px]">
          {/* Sidebar */}
          <div className="w-64 bg-[#EBF0F5] p-6 shrink-0 hidden sm:block border-r border-[#D0D7DE]/40">
            <div className="space-y-2.5">
              {STEPS.map((label, i) => {
                const done = i < step
                const active = i === step
                return (
                  <div
                    key={i}
                    className={`px-4 py-2.5 rounded-xl text-xs font-bold flex items-center gap-3 transition-all ${
                      active
                        ? 'bg-[#F4F7FA] text-[#0066A1] shadow-[inset_0_2px_4px_rgba(255,255,255,0.8),_0_4px_10px_rgba(0,0,0,0.04)] border border-white'
                        : done
                        ? 'text-[#57606A] opacity-70'
                        : 'text-[#8C959F] opacity-50'
                    }`}
                  >
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] shrink-0 ${
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

          {/* Content */}
          <div className="flex-1 flex flex-col bg-[#F8FAFC] shadow-[inset_4px_0_12px_rgba(0,0,0,0.02)]">
            <div className="flex-1 p-8 overflow-y-auto">
              {step === STEP_CLINIC && <StepClinic data={clinic} onChange={updateClinic} />}
              {step === STEP_PROFESSIONAL && <StepProfessional data={professional} onChange={updateProfessional} />}
              {step === STEP_SCHEDULE && <StepSchedule data={professional} onChange={updateProfessional} />}
              {step === STEP_PLAN && <StepPlan data={plan} onChange={updatePlan} onSkip={goToPlanSkip} />}
              {step === STEP_MODULES && <StepModules active={modules} loading={modulesLoading} />}
              {step === STEP_DPA && <StepDpa status={dpa} loading={dpaLoading} />}
              {step === STEP_DONE && <StepComplete />}

              {error && (
                <div className="mt-6 px-4 py-3 bg-[#FFEBE9] border border-[#FF8182]/50 shadow-[inset_0_2px_4px_rgba(255,255,255,0.5),_0_2px_8px_rgba(207,34,46,0.1)] text-[#CF222E] text-xs font-bold rounded-xl">
                  Não foi possível salvar: {error}
                </div>
              )}
            </div>

            {/* Footer */}
            {step < STEP_DONE && (
              <div className="bg-[#F4F7FA] border-t border-white px-8 py-5 flex justify-between items-center shadow-[0_-4px_15px_rgba(0,0,0,0.02)] z-10">
                <button
                  onClick={() => { setError(null); setStep((s) => Math.max(0, s - 1)) }}
                  disabled={step === 0 || saving}
                  className="px-5 py-2 text-xs font-bold text-[#57606A] bg-[#E8EDF2] rounded-lg shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),_0_2px_5px_rgba(0,0,0,0.05)] hover:bg-[#dfe5ea] disabled:opacity-40 transition-all"
                >
                  Voltar
                </button>
                <button
                  onClick={handleNext}
                  disabled={!canNext()}
                  className="px-8 py-2 text-xs font-bold text-white bg-gradient-to-b from-[#0066A1] to-[#005282] rounded-lg border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] disabled:opacity-50 transition-all min-w-[140px]"
                >
                  {nextLabel()}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
