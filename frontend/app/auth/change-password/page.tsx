'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Lock } from 'lucide-react'
import { getAccessToken } from '@/lib/auth'

export default function ChangePasswordPage() {
  const router = useRouter()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Client-side validation
    if (newPassword.length < 8) {
      setError('A nova senha deve ter no mínimo 8 caracteres.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('As senhas não coincidem.')
      return
    }
    if (newPassword === currentPassword) {
      setError('A nova senha deve ser diferente da atual.')
      return
    }

    setSubmitting(true)
    try {
      const token = getAccessToken()
      const res = await fetch('/api/v1/auth/password', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })

      if (res.ok) {
        // must_change_password flag cleared server-side; navigate to dashboard
        router.push('/dashboard')
        router.refresh()
        return
      }

      const body = await res.json().catch(() => ({}))
      const message =
        body?.error?.message ?? body?.detail ?? 'Erro ao alterar a senha. Verifique a senha atual.'
      setError(message)
    } catch {
      setError('Falha de conexão. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen bg-neu-app flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-neu-outer border border-white rounded-2xl shadow-neu-modal p-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-full bg-neu-input shadow-neu-inset flex items-center justify-center text-neu-brand">
            <Lock size={20} />
          </div>
          <h1 className="text-xl font-semibold text-neu-ink">Altere sua senha temporária</h1>
        </div>
        <p className="text-sm text-neu-inkSoft mb-6">
          Sua senha foi definida pelo administrador da clínica. Por segurança, você precisa
          escolher uma nova senha antes de continuar.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field
            label="Senha atual (temporária)"
            value={currentPassword}
            onChange={setCurrentPassword}
            autoComplete="current-password"
          />
          <Field
            label="Nova senha"
            value={newPassword}
            onChange={setNewPassword}
            autoComplete="new-password"
            hint="Mínimo de 8 caracteres."
          />
          <Field
            label="Confirme a nova senha"
            value={confirmPassword}
            onChange={setConfirmPassword}
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
            disabled={submitting || !currentPassword || !newPassword || !confirmPassword}
            className="w-full neu-btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Alterando...' : 'Alterar senha'}
          </button>
        </form>
      </div>
    </main>
  )
}

function Field({
  label,
  value,
  onChange,
  autoComplete,
  hint,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  autoComplete?: string
  hint?: string
}) {
  // Stable id from label so getByLabelText can link <label htmlFor> to <input id>.
  const id = `field-${label
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')}`
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
      {hint && <p className="mt-1 text-xs text-neu-inkMuted">{hint}</p>}
    </div>
  )
}
