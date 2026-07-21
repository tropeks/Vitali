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
      const res = await fetch(`/api/auth/set-password/${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })

      if (res.ok) {
        router.push('/dashboard')
        router.refresh()
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
    <main className="min-h-screen bg-neu-app flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-neu-outer border border-white rounded-2xl shadow-neu-modal p-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-full bg-neu-input shadow-neu-inset flex items-center justify-center text-neu-brand">
            <KeyRound size={20} />
          </div>
          <h1 className="text-xl font-semibold text-neu-ink">Defina sua senha</h1>
        </div>
        <p className="text-sm text-neu-inkSoft mb-6">
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
              className="text-sm text-neu-danger bg-neu-danger/10 border border-neu-danger/20 rounded-lg px-3 py-2"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !password || !confirm}
            className="w-full neu-btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Definindo...' : 'Definir senha e entrar'}
          </button>
        </form>

        <p className="mt-6 text-xs text-neu-inkMuted text-center">
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
      <label htmlFor={id} className="neu-label">
        {label}
      </label>
      <input
        id={id}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required
        className="neu-input"
      />
    </div>
  )
}
