'use client'

/**
 * S-132: Public self-serve clinic signup.
 *
 * Marketing intro + a 3-field form (company, CNPJ, email). On success the
 * backend provisions a trial tenant and emails the owner a set-password link,
 * so this page just confirms and tells them to check their inbox — no password
 * is collected here (the welcome link activates the account).
 */

import { useState } from 'react'
import Link from 'next/link'
import { Building2, CheckCircle2, ShieldCheck, Clock, Mail } from 'lucide-react'

const BENEFITS = [
  { icon: Clock, title: 'Pronto em minutos', body: 'Sua clínica funcional sem espera por engenharia.' },
  { icon: ShieldCheck, title: '14 dias de trial', body: 'Teste todos os recursos antes de pagar.' },
  { icon: Building2, title: 'Ambiente isolado', body: 'Dados da sua clínica em um schema dedicado.' },
]

interface SignupSuccess {
  domain: string
  owner_email: string
  message: string
}

/** Light CNPJ mask: 00.000.000/0000-00 while typing. */
function maskCnpj(raw: string): string {
  const d = raw.replace(/\D/g, '').slice(0, 14)
  let out = d
  if (d.length > 12) out = `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`
  else if (d.length > 8) out = `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8)}`
  else if (d.length > 5) out = `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5)}`
  else if (d.length > 2) out = `${d.slice(0, 2)}.${d.slice(2)}`
  return out
}

export default function SignupPage() {
  const [companyName, setCompanyName] = useState('')
  const [cnpj, setCnpj] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({})
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState<SignupSuccess | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setFieldErrors({})
    setSubmitting(true)
    try {
      const res = await fetch('/api/v1/public/signup/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_name: companyName, cnpj, email }),
      })
      const body = await res.json().catch(() => ({}))

      if (res.status === 201) {
        setSuccess(body as SignupSuccess)
        return
      }
      if (res.status === 409) {
        setError(body?.error?.message ?? 'Já existe uma conta com este e-mail.')
        return
      }
      if (res.status === 400) {
        setFieldErrors(body?.error?.details ?? {})
        setError('Confira os dados do formulário.')
        return
      }
      setError(body?.error?.message ?? 'Não foi possível concluir o cadastro. Tente novamente.')
    } catch {
      setError('Erro de conexão. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-sm p-8 text-center">
          <div className="mx-auto w-12 h-12 rounded-full bg-green-50 flex items-center justify-center text-green-600 mb-4">
            <CheckCircle2 size={26} />
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Clínica criada!</h1>
          <p className="mt-2 text-sm text-slate-500">{success.message}</p>
          <div className="mt-5 flex items-center justify-center gap-2 text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
            <Mail size={16} className="text-slate-400" />
            <span className="font-medium break-all">{success.owner_email}</span>
          </div>
          <p className="mt-6 text-xs text-slate-400">
            Já definiu sua senha?{' '}
            <Link href="/login" className="text-blue-600 hover:underline">
              Fazer login
            </Link>
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-slate-50 grid lg:grid-cols-2">
      {/* Marketing column */}
      <section className="hidden lg:flex flex-col justify-center gap-8 p-12 bg-gradient-to-br from-blue-600 to-blue-800 text-white">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-200">Vitali</p>
          <h2 className="mt-3 text-3xl font-semibold leading-tight">
            A gestão da sua clínica, no ar em minutos.
          </h2>
          <p className="mt-3 text-blue-100">
            Prontuário, agenda e cobrança em um só lugar. Cadastre-se e comece o trial sem falar com
            ninguém.
          </p>
        </div>
        <ul className="space-y-5">
          {BENEFITS.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex gap-3">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/10">
                <Icon size={18} />
              </span>
              <div>
                <p className="font-medium">{title}</p>
                <p className="text-sm text-blue-100">{body}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* Form column */}
      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-sm p-8">
          <h1 className="text-xl font-semibold text-slate-900">Crie sua clínica</h1>
          <p className="mt-1 text-sm text-slate-500">
            Comece grátis. Sem cartão de crédito para o trial.
          </p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            <Field
              label="Nome da clínica"
              id="company_name"
              value={companyName}
              onChange={setCompanyName}
              placeholder="Clínica Vida"
              autoComplete="organization"
              errors={fieldErrors.company_name}
            />
            <Field
              label="CNPJ"
              id="cnpj"
              value={cnpj}
              onChange={(v) => setCnpj(maskCnpj(v))}
              placeholder="00.000.000/0000-00"
              inputMode="numeric"
              errors={fieldErrors.cnpj}
            />
            <Field
              label="E-mail do responsável"
              id="email"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="voce@clinica.com.br"
              autoComplete="email"
              errors={fieldErrors.email}
            />

            {error && (
              <div
                role="alert"
                className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting || !companyName || !cnpj || !email}
              className="w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? 'Criando sua clínica...' : 'Criar clínica e começar trial'}
            </button>
          </form>

          <p className="mt-6 text-xs text-slate-400 text-center">
            Ao criar, você concorda com nossos termos.{' '}
            <Link href="/login" className="text-blue-600 hover:underline">
              Já tem conta?
            </Link>
          </p>
        </div>
      </section>
    </main>
  )
}

function Field({
  label,
  id,
  value,
  onChange,
  type = 'text',
  placeholder,
  autoComplete,
  inputMode,
  errors,
}: {
  label: string
  id: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  autoComplete?: string
  inputMode?: 'numeric' | 'text'
  errors?: string[]
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-700 mb-1">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        inputMode={inputMode}
        required
        aria-invalid={errors != null && errors.length > 0}
        className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {errors?.length ? <p className="mt-1 text-xs text-red-600">{errors[0]}</p> : null}
    </div>
  )
}
