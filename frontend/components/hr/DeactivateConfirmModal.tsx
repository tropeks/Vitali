'use client'

import { useState } from 'react'
import { X, AlertTriangle } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import type { Employee } from '@/app/(dashboard)/rh/funcionarios/page'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DeactivateConfirmModalProps {
  open: boolean
  employee: Employee | null
  onClose: () => void
  onDeactivated: (messages: string[]) => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function DeactivateConfirmModal({
  open,
  employee,
  onClose,
  onDeactivated,
}: DeactivateConfirmModalProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open || !employee) return null

  const handleDeactivate = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await apiFetch<{
        employment_status?: string
        tokens_revoked?: number
        professional_deactivated?: boolean
        user_deactivated?: boolean
        [key: string]: unknown
      }>(`/api/v1/hr/employees/${employee.id}/`, {
        method: 'DELETE',
      })

      // Build success messages from server response side effects
      const msgs: string[] = ['Funcionário desativado ✓']
      if (result && typeof result === 'object') {
        if (typeof result.tokens_revoked === 'number' && result.tokens_revoked > 0) {
          msgs.push(`${result.tokens_revoked} tokens revogados ✓`)
        }
        if (result.professional_deactivated) {
          msgs.push('Profissional desativado ✓')
        }
        if (result.user_deactivated) {
          msgs.push('Conta inativada ✓')
        }
      }

      onDeactivated(msgs)
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body
        if (typeof body === 'object' && body?.detail) {
          setError(String(body.detail))
        } else {
          setError('Erro ao desativar funcionário. Tente novamente.')
        }
      } else {
        setError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-md w-full">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
              <AlertTriangle size={20} className="text-red-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-900">Desativar funcionário</h2>
              <p className="text-xs text-slate-500 mt-0.5">{employee.full_name}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={loading}
            className="text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        {/* Warning copy */}
        <div className="space-y-3 text-sm text-slate-700">
          <p>
            Tem certeza que deseja desativar{' '}
            <strong className="text-slate-900">{employee.full_name}</strong>?
          </p>

          <p className="text-slate-600">O funcionário será desativado de forma reversível:</p>

          <ul className="space-y-1.5 pl-4">
            <li className="flex items-start gap-2">
              <span className="text-slate-400 mt-0.5">•</span>
              <span>Sua conta será inativada</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-slate-400 mt-0.5">•</span>
              <span>Tokens de acesso serão revogados</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-slate-400 mt-0.5">•</span>
              <span>Cadastro profissional (se houver) será desativado</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-slate-400 mt-0.5">•</span>
              <span>
                Prontuários assinados permanecem atribuídos a este profissional (CFM Res. 1.821)
              </span>
            </li>
          </ul>

          <p className="text-slate-500 text-xs">
            Você pode reativar o funcionário a qualquer momento.
          </p>
        </div>

        {/* Footer */}
        <div className="flex gap-3 mt-6 pt-4 border-t border-slate-100 justify-end">
          <button
            onClick={onClose}
            disabled={loading}
            className="border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleDeactivate}
            disabled={loading}
            className="bg-red-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Desativando...' : 'Desativar'}
          </button>
        </div>
      </div>
    </div>
  )
}
