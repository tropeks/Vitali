'use client'

import { useState } from 'react'
import { X, Copy, Check } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { formatCPF } from '@/lib/formatters'

// ─── Types ────────────────────────────────────────────────────────────────────

export type EmployeeRole =
  | 'admin'
  | 'medico'
  | 'enfermeiro'
  | 'recepcao'
  | 'faturista'
  | 'farmaceutico'
  | 'dentista'

export type ContractType = 'clt' | 'pj' | 'autonomo' | 'estagiario'
export type EmploymentStatus = 'active' | 'on_leave' | 'terminated'
export type CouncilType = 'CRM' | 'COREN' | 'CRF' | 'CRO'
export type AuthMode = 'typed_password' | 'random_password' | 'invite'

export interface Employee {
  employee_id: string
  user_id: string
  professional_id: string | null
  whatsapp_setup_queued: boolean
  correlation_id: string
}

interface Form {
  // Step 1
  full_name: string
  email: string
  cpf: string
  phone: string
  // Step 2
  role: EmployeeRole
  hire_date: string
  contract_type: ContractType
  employment_status: EmploymentStatus
  council_type: CouncilType | ''
  council_number: string
  council_state: string
  specialty: string
  // Step 3
  auth_mode: AuthMode | ''
  password: string
  setup_whatsapp: boolean
}

export interface AddEmployeeModalProps {
  open: boolean
  onClose: () => void
  onSuccess?: (employee: Employee) => void
}

// ─── Constants ────────────────────────────────────────────────────────────────

const CLINICAL_ROLES: EmployeeRole[] = ['medico', 'enfermeiro', 'farmaceutico', 'dentista']

const ROLE_LABELS: Record<EmployeeRole, string> = {
  admin: 'Administrador',
  medico: 'Médico',
  enfermeiro: 'Enfermeiro(a)',
  recepcao: 'Recepcionista',
  faturista: 'Faturista',
  farmaceutico: 'Farmacêutico(a)',
  dentista: 'Dentista',
}

const CONTRACT_LABELS: Record<ContractType, string> = {
  clt: 'CLT',
  pj: 'PJ',
  autonomo: 'Autônomo',
  estagiario: 'Estagiário',
}

const STATUS_LABELS: Record<EmploymentStatus, string> = {
  active: 'Ativo',
  on_leave: 'Afastado',
  terminated: 'Desligado',
}

const COUNCIL_TYPES: CouncilType[] = ['CRM', 'COREN', 'CRF', 'CRO']

const UF_STATES = [
  'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO',
  'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI',
  'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
]

// ─── Password generator ───────────────────────────────────────────────────────

function generatePassword(): string {
  const charset = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%&*?'
  const arr = new Uint32Array(16)
  crypto.getRandomValues(arr)
  return Array.from(arr, n => charset[n % charset.length]).join('')
}

// ─── Field-level error extraction ─────────────────────────────────────────────

function extractFieldErrors(body: any): Record<string, string> {
  if (!body || typeof body !== 'object') return {}
  const errors: Record<string, string> = {}
  for (const [key, val] of Object.entries(body)) {
    if (Array.isArray(val) && val.length > 0) {
      errors[key] = String(val[0])
    } else if (typeof val === 'string') {
      errors[key] = val
    }
  }
  return errors
}

// ─── Shared input / select classes ───────────────────────────────────────────

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder:text-gray-400'
const SELECT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white'
const LABEL_CLASS = 'block text-xs font-medium text-gray-700 mb-1'
const PRIMARY_BTN =
  'bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
const SECONDARY_BTN =
  'border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors'

// ─── Initial form state ───────────────────────────────────────────────────────

const INITIAL_FORM: Form = {
  full_name: '',
  email: '',
  cpf: '',
  phone: '',
  role: 'recepcao',
  hire_date: '',
  contract_type: 'clt',
  employment_status: 'active',
  council_type: '',
  council_number: '',
  council_state: '',
  specialty: '',
  auth_mode: '',
  password: '',
  setup_whatsapp: false,
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function AddEmployeeModal({ open, onClose, onSuccess }: AddEmployeeModalProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [form, setForm] = useState<Form>(INITIAL_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [globalError, setGlobalError] = useState('')
  const [toasts, setToasts] = useState<string[]>([])
  const [copied, setCopied] = useState(false)

  if (!open) return null

  // ── Derived state ──────────────────────────────────────────────────────────

  const isClinical = CLINICAL_ROLES.includes(form.role as EmployeeRole)

  const step1Valid =
    form.full_name.trim().length > 0 &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email) &&
    form.cpf.replace(/\D/g, '').length === 11

  const step2Valid =
    !isClinical ||
    (form.council_type !== '' && form.council_number.trim() !== '' && form.council_state !== '')

  const step3Valid =
    form.auth_mode !== '' &&
    (form.auth_mode === 'invite' || form.password.trim().length > 0)

  // ── Helpers ────────────────────────────────────────────────────────────────

  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm(f => ({ ...f, [key]: value }))

  const handleClose = () => {
    setStep(1)
    setForm(INITIAL_FORM)
    setFieldErrors({})
    setGlobalError('')
    setToasts([])
    onClose()
  }

  const handleGenerate = () => {
    set('password', generatePassword())
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(form.password)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // silently fail if clipboard not available (e.g. test env)
    }
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setFieldErrors({})
    setGlobalError('')

    const payload: Record<string, unknown> = {
      full_name: form.full_name.trim(),
      email: form.email.trim(),
      cpf: form.cpf.replace(/\D/g, ''),
      phone: form.phone.trim() || undefined,
      role: form.role,
      hire_date: form.hire_date || undefined,
      contract_type: form.contract_type,
      employment_status: form.employment_status,
      auth_mode: form.auth_mode,
      setup_whatsapp: form.setup_whatsapp,
    }

    if (isClinical) {
      payload.council_type = form.council_type || undefined
      payload.council_number = form.council_number.trim() || undefined
      payload.council_state = form.council_state || undefined
      payload.specialty = form.specialty.trim() || undefined
    }

    if (form.auth_mode === 'typed_password' || form.auth_mode === 'random_password') {
      payload.password = form.password
    }

    try {
      const employee = await apiFetch<Employee>('/api/v1/hr/employees/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })

      // Build success toasts
      const msgs: string[] = ['Funcionário criado ✓']
      if (isClinical) msgs.push('Profissional cadastrado ✓')
      if (form.auth_mode === 'invite') msgs.push('Convite enviado ✓')
      if (form.setup_whatsapp && employee.whatsapp_setup_queued) msgs.push('WhatsApp na fila ✓')
      setToasts(msgs)

      onSuccess?.(employee)

      // Auto-close after showing toasts
      setTimeout(() => handleClose(), 2500)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setFieldErrors(extractFieldErrors(err.body))
        const first = Object.values(extractFieldErrors(err.body))[0]
        setGlobalError(first ?? 'Erro ao cadastrar funcionário.')
      } else {
        setGlobalError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  // ── Render helpers ─────────────────────────────────────────────────────────

  const FieldError = ({ field }: { field: string }) =>
    fieldErrors[field] ? (
      <p className="text-xs text-red-600 mt-1">{fieldErrors[field]}</p>
    ) : null

  // ── Step 1 ─────────────────────────────────────────────────────────────────

  const renderStep1 = () => (
    <div className="space-y-4">
      <div>
        <label htmlFor="full_name" className={LABEL_CLASS}>
          Nome completo <span className="text-red-500">*</span>
        </label>
        <input
          id="full_name"
          type="text"
          className={INPUT_CLASS}
          value={form.full_name}
          onChange={e => set('full_name', e.target.value)}
          placeholder="Ex.: Maria Silva"
        />
        <FieldError field="full_name" />
      </div>

      <div>
        <label htmlFor="email" className={LABEL_CLASS}>
          E-mail <span className="text-red-500">*</span>
        </label>
        <input
          id="email"
          type="email"
          className={INPUT_CLASS}
          value={form.email}
          onChange={e => set('email', e.target.value)}
          placeholder="funcionario@clinica.com.br"
        />
        <FieldError field="email" />
      </div>

      <div>
        <label htmlFor="cpf" className={LABEL_CLASS}>
          CPF <span className="text-red-500">*</span>
        </label>
        <input
          id="cpf"
          type="text"
          inputMode="numeric"
          className={INPUT_CLASS}
          value={form.cpf}
          onChange={e => set('cpf', formatCPF(e.target.value))}
          placeholder="000.000.000-00"
          maxLength={14}
        />
        <FieldError field="cpf" />
      </div>

      <div>
        <label htmlFor="phone" className={LABEL_CLASS}>
          Telefone <span className="text-gray-400 font-normal">(opcional)</span>
        </label>
        <input
          id="phone"
          type="tel"
          className={INPUT_CLASS}
          value={form.phone}
          onChange={e => set('phone', e.target.value)}
          placeholder="+5511999999999"
        />
        <FieldError field="phone" />
      </div>
    </div>
  )

  // ── Step 2 ─────────────────────────────────────────────────────────────────

  const renderStep2 = () => (
    <div className="space-y-4">
      <div>
        <label htmlFor="role" className={LABEL_CLASS}>
          Função <span className="text-red-500">*</span>
        </label>
        <select
          id="role"
          className={SELECT_CLASS}
          value={form.role}
          onChange={e => {
            set('role', e.target.value as EmployeeRole)
            // Clear council fields when switching away from clinical
            if (!CLINICAL_ROLES.includes(e.target.value as EmployeeRole)) {
              setForm(f => ({ ...f, role: e.target.value as EmployeeRole, council_type: '', council_number: '', council_state: '', specialty: '' }))
            }
          }}
        >
          {(Object.keys(ROLE_LABELS) as EmployeeRole[]).map(r => (
            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
          ))}
        </select>
        <FieldError field="role" />
      </div>

      <div>
        <label htmlFor="hire_date" className={LABEL_CLASS}>
          Data de admissão
        </label>
        <input
          id="hire_date"
          type="date"
          className={INPUT_CLASS}
          value={form.hire_date}
          onChange={e => set('hire_date', e.target.value)}
        />
        <FieldError field="hire_date" />
      </div>

      <div>
        <label htmlFor="contract_type" className={LABEL_CLASS}>
          Tipo de contrato <span className="text-red-500">*</span>
        </label>
        <select
          id="contract_type"
          className={SELECT_CLASS}
          value={form.contract_type}
          onChange={e => set('contract_type', e.target.value as ContractType)}
        >
          {(Object.keys(CONTRACT_LABELS) as ContractType[]).map(c => (
            <option key={c} value={c}>{CONTRACT_LABELS[c]}</option>
          ))}
        </select>
        <FieldError field="contract_type" />
      </div>

      <div>
        <label htmlFor="employment_status" className={LABEL_CLASS}>
          Status <span className="text-red-500">*</span>
        </label>
        <select
          id="employment_status"
          className={SELECT_CLASS}
          value={form.employment_status}
          onChange={e => set('employment_status', e.target.value as EmploymentStatus)}
        >
          {(Object.keys(STATUS_LABELS) as EmploymentStatus[]).map(s => (
            <option key={s} value={s}>{STATUS_LABELS[s]}</option>
          ))}
        </select>
        <FieldError field="employment_status" />
      </div>

      {isClinical && (
        <div className="border border-blue-200 bg-blue-50 rounded-xl p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-800">Conselho Profissional</h3>

          <div>
            <label htmlFor="council_type" className={LABEL_CLASS}>
              Conselho <span className="text-red-500">*</span>
            </label>
            <select
              id="council_type"
              className={SELECT_CLASS}
              value={form.council_type}
              onChange={e => set('council_type', e.target.value as CouncilType)}
            >
              <option value="">Selecione...</option>
              {COUNCIL_TYPES.map(ct => (
                <option key={ct} value={ct}>{ct}</option>
              ))}
            </select>
            <FieldError field="council_type" />
          </div>

          <div>
            <label htmlFor="council_number" className={LABEL_CLASS}>
              Número <span className="text-red-500">*</span>
            </label>
            <input
              id="council_number"
              type="text"
              className={INPUT_CLASS}
              value={form.council_number}
              onChange={e => set('council_number', e.target.value)}
              placeholder="Ex.: 123456"
            />
            <FieldError field="council_number" />
          </div>

          <div>
            <label htmlFor="council_state" className={LABEL_CLASS}>
              UF <span className="text-red-500">*</span>
            </label>
            <select
              id="council_state"
              className={SELECT_CLASS}
              value={form.council_state}
              onChange={e => set('council_state', e.target.value)}
            >
              <option value="">Selecione...</option>
              {UF_STATES.map(uf => (
                <option key={uf} value={uf}>{uf}</option>
              ))}
            </select>
            <FieldError field="council_state" />
          </div>

          <div>
            <label htmlFor="specialty" className={LABEL_CLASS}>
              Especialidade <span className="text-gray-400 font-normal">(opcional)</span>
            </label>
            <input
              id="specialty"
              type="text"
              className={INPUT_CLASS}
              value={form.specialty}
              onChange={e => set('specialty', e.target.value)}
              placeholder="Ex.: Cardiologia"
            />
          </div>
        </div>
      )}
    </div>
  )

  // ── Step 3 ─────────────────────────────────────────────────────────────────

  const renderStep3 = () => {
    const phoneEmpty = form.phone.trim() === ''

    return (
      <div className="space-y-4">
        {/* Auth mode radio group */}
        <div className="space-y-3">
          <p className={LABEL_CLASS}>Acesso inicial <span className="text-red-500">*</span></p>

          {/* Option 1: typed password */}
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="radio"
              name="auth_mode"
              value="typed_password"
              checked={form.auth_mode === 'typed_password'}
              onChange={() => set('auth_mode', 'typed_password')}
              className="mt-0.5 h-4 w-4 text-blue-600 border-slate-300 focus:ring-blue-500"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-slate-800">Definir senha temporária</span>
              {form.auth_mode === 'typed_password' && (
                <div className="mt-2">
                  <input
                    id="password"
                    type="text"
                    className={INPUT_CLASS}
                    value={form.password}
                    onChange={e => set('password', e.target.value)}
                    placeholder="Senha temporária"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    O funcionário deverá alterar a senha no primeiro login.
                  </p>
                </div>
              )}
            </div>
          </label>

          {/* Option 2: random password */}
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="radio"
              name="auth_mode"
              value="random_password"
              checked={form.auth_mode === 'random_password'}
              onChange={() => set('auth_mode', 'random_password')}
              className="mt-0.5 h-4 w-4 text-blue-600 border-slate-300 focus:ring-blue-500"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-slate-800">Gerar senha aleatória</span>
              {form.auth_mode === 'random_password' && (
                <div className="mt-2 space-y-2">
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={handleGenerate}
                      className="px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-medium transition-colors"
                    >
                      Gerar
                    </button>
                    {form.password && (
                      <button
                        type="button"
                        onClick={handleCopy}
                        className="flex items-center gap-1 px-3 py-1.5 text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-medium transition-colors"
                      >
                        {copied ? <Check size={12} /> : <Copy size={12} />}
                        {copied ? 'Copiado' : 'Copiar'}
                      </button>
                    )}
                  </div>
                  {form.password && (
                    <input
                      id="generated_password"
                      type="text"
                      readOnly
                      className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm font-mono bg-slate-50"
                      value={form.password}
                      aria-label="Senha gerada"
                    />
                  )}
                </div>
              )}
            </div>
          </label>

          {/* Option 3: invite */}
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="radio"
              name="auth_mode"
              value="invite"
              checked={form.auth_mode === 'invite'}
              onChange={() => {
                set('auth_mode', 'invite')
                set('password', '')
              }}
              className="mt-0.5 h-4 w-4 text-blue-600 border-slate-300 focus:ring-blue-500"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-slate-800">Enviar convite por e-mail</span>
              {form.auth_mode === 'invite' && (
                <p className="text-xs text-gray-500 mt-1">
                  O servidor enviará um link de convite para o e-mail cadastrado.
                </p>
              )}
            </div>
          </label>
        </div>

        {/* WhatsApp checkbox */}
        <div className="border-t border-slate-100 pt-4">
          <label className={`flex items-start gap-3 ${phoneEmpty ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}>
            <input
              type="checkbox"
              checked={form.setup_whatsapp}
              disabled={phoneEmpty}
              onChange={e => set('setup_whatsapp', e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-50"
              aria-label="Configurar WhatsApp para comunicação interna"
            />
            <div>
              <span className="text-sm text-slate-700">
                Configurar WhatsApp para comunicação interna
              </span>
              {phoneEmpty && (
                <p className="text-xs text-gray-400 mt-0.5">
                  Preencha o telefone na etapa 1 para habilitar.
                </p>
              )}
            </div>
          </label>
        </div>
      </div>
    )
  }

  // ── Main render ────────────────────────────────────────────────────────────

  const canProceedStep1 = step1Valid
  const canProceedStep2 = step2Valid
  const canSubmit = step3Valid && !submitting

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-lg w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Novo Funcionário</h2>
            <p className="text-xs text-slate-500 mt-0.5">Etapa {step} de 3</p>
          </div>
          <button
            onClick={handleClose}
            disabled={submitting}
            className="text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex gap-1.5 mb-5">
          {([1, 2, 3] as const).map(s => (
            <div
              key={s}
              className={`h-1 flex-1 rounded-full transition-colors ${
                s <= step ? 'bg-blue-600' : 'bg-slate-200'
              }`}
            />
          ))}
        </div>

        {/* Toasts */}
        {toasts.length > 0 && (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg space-y-1">
            {toasts.map((t, i) => (
              <p key={i} className="text-sm text-green-700 font-medium">{t}</p>
            ))}
          </div>
        )}

        {/* Global error */}
        {globalError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">{globalError}</p>
          </div>
        )}

        {/* Step content */}
        <div className="flex-1 overflow-y-auto">
          {step === 1 && renderStep1()}
          {step === 2 && renderStep2()}
          {step === 3 && renderStep3()}
        </div>

        {/* Footer nav */}
        <div className="flex items-center justify-between mt-5 pt-4 border-t border-slate-100">
          <button
            onClick={step === 1 ? handleClose : () => setStep((step - 1) as 1 | 2)}
            disabled={submitting}
            className={SECONDARY_BTN}
          >
            {step === 1 ? 'Cancelar' : 'Voltar'}
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep((step + 1) as 2 | 3)}
              disabled={step === 1 ? !canProceedStep1 : !canProceedStep2}
              className={PRIMARY_BTN}
            >
              Próximo
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!canSubmit}
              className={PRIMARY_BTN}
            >
              {submitting ? 'Cadastrando...' : 'Cadastrar Funcionário'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
