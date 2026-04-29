'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { KeyRound } from 'lucide-react'

export default function SetPasswordPage() {
  const params = useParams<{ token: string }>()
  const router = useRouter()
  const token = params.token

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (password.length < 8) {
      setError('A senha deve ter no mínimo 8 caracteres.')
      return
    }
    if (password !== confirm) {
      setError('As senhas não conferem.')
      return
    }

    setSubmitting(true)
    try {
      const res = await fetch(`/api/v1/auth/set-password/${token}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })

      if (res.ok) {
        const { access, refresh } = await res.json()
        localStorage.setItem('access_token', access)
        localStorage.setItem('refresh_token', refresh)
        router.push('/dashboard')
        return
      }

      if (res.status === 410) {
        setError(
          'Este link de convite expirou. Peça um novo convite ao administrador da sua clínica.',
        )
      } else if (res.status === 400) {
        const body = await res.json().catch(() => ({}))
        if (body.error === 'INVITATION_ALREADY_CONSUMED') {
          setError('Este link já foi usado. Use sua senha para fazer login.')
        } else if (body.error === 'PASSWORD_TOO_SHORT') {
          setError('A senha deve ter no mínimo 8 caracteres.')
        } else {
          setError('Link de convite inválido. Peça um novo convite ao administrador.')
        }
      } else {
        setError('Erro ao definir senha. Tente novamente.')
      }
    } catch {
      setError('Erro de conexão. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-sm p-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">
            <KeyRound size={20} />
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Defina sua senha</h1>
        </div>
        <p className="text-sm text-slate-500 mb-6">
          Crie uma senha para acessar sua conta na Vitali. Mínimo 8 caracteres.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <PasswordField
            label="Nova senha"
            id="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
          />
          <PasswordField
            label="Confirmar senha"
            id="confirm"
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
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
            disabled={submitting || !password || !confirm}
            className="w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Definindo...' : 'Definir senha e entrar'}
          </button>
        </form>

        <p className="mt-6 text-xs text-slate-400 text-center">
          Problemas com o link? Entre em contato com o administrador da sua clínica.
        </p>
      </div>
    </main>
  )
}

function PasswordField({
  label,
  id,
  value,
  onChange,
  autoComplete,
}: {
  label: string
  id: string
  value: string
  onChange: (v: string) => void
  autoComplete?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-700 mb-1">
        {label}
      </label>
      <input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required
        className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  )
}
