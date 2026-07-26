'use client'

import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import type { Position } from '@/app/(dashboard)/rh/cargos/page'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PositionFormModalProps {
  open: boolean
  position: Position | null
  onClose: () => void
  onSuccess: () => void
}

// ─── Shared input classes ─────────────────────────────────────────────────────

const INPUT_CLASS =
  'w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent'
const LABEL_CLASS = 'block text-xs font-medium text-slate-700 mb-1'

// ─── Field error extraction ───────────────────────────────────────────────────

function extractError(err: any): string {
  if (typeof err === 'string') return err
  if (err?.detail) return String(err.detail)
  const firstVal = Object.values(err ?? {})[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao salvar. Tente novamente.'
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PositionFormModal({
  open,
  position,
  onClose,
  onSuccess,
}: PositionFormModalProps) {
  const [title, setTitle] = useState('')
  const [cbo, setCbo] = useState('')
  const [active, setActive] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isEditing = position !== null

  // Sync form with incoming position (or reset for create) whenever the modal opens
  useEffect(() => {
    if (open) {
      setTitle(position?.title ?? '')
      setCbo(position?.cbo ?? '')
      setActive(position?.active ?? true)
      setError(null)
    }
  }, [open, position])

  if (!open) return null

  const canSubmit = title.trim().length > 0 && !saving

  async function handleSubmit() {
    setSaving(true)
    setError(null)

    const payload = {
      title: title.trim(),
      cbo: cbo.trim(),
      active,
    }

    try {
      if (isEditing && position) {
        await apiFetch(`/api/v1/hr/positions/${position.id}/`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })
      } else {
        await apiFetch('/api/v1/hr/positions/', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
      }
      onSuccess()
    } catch (err) {
      if (err instanceof ApiError) {
        setError(extractError(err.body))
      } else {
        setError('Erro inesperado. Tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50">
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-slate-900">
            {isEditing ? 'Editar Cargo' : 'Novo Cargo'}
          </h2>
          <button
            onClick={onClose}
            disabled={saving}
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

        {/* Form */}
        <div className="space-y-4">
          <div>
            <label htmlFor="position-title" className={LABEL_CLASS}>
              Título <span className="text-red-500">*</span>
            </label>
            <input
              id="position-title"
              type="text"
              className={INPUT_CLASS}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex.: Recepcionista"
            />
          </div>

          <div>
            <label htmlFor="position-cbo" className={LABEL_CLASS}>
              CBO <span className="text-slate-400 font-normal">(opcional)</span>
            </label>
            <input
              id="position-cbo"
              type="text"
              className={INPUT_CLASS}
              value={cbo}
              onChange={(e) => setCbo(e.target.value)}
              placeholder="Ex.: 4221-05"
            />
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-slate-700">Cargo ativo</span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-slate-100">
          <button
            onClick={onClose}
            disabled={saving}
            className="border border-slate-200 text-slate-700 rounded-lg px-4 py-2 text-sm font-medium hover:bg-slate-50 transition-colors disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? 'Salvando...' : isEditing ? 'Salvar' : 'Cadastrar Cargo'}
          </button>
        </div>
      </div>
    </div>
  )
}
