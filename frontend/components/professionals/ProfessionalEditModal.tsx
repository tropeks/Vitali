'use client'

import { useState, type FormEvent } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { Button, SectionState } from '@/components/shared'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import type { Professional } from './ProfessionalRow'

// A1 — governed CBO/CNES search+select for a Professional. Reuses the shared
// RemoteCombobox against the terminology autocomplete endpoints (A1-T4):
// GET /api/v1/terminology/<cbo|cnes>/?q=<text> → { results: [{code, display, ...}] }.
// Saving PATCHes cbo_code/cnes_code as plain strings; the server reconciles
// them to the governed FK and recomputes cbo_unmatched/cnes_unmatched.

export interface TerminologyResult {
  system: string
  code: string
  display: string
  active: boolean
  context?: string | null
}

interface Props {
  professional: Professional
  onClose: () => void
  onSaved: (updated: Professional) => void
}

// Until the user searches, show the stored raw code as its own label (we have
// no cached display text for it) — a search + pick replaces it with the
// governed catalog's `display`.
function initialResult(code: string | null, system: string): TerminologyResult | null {
  if (!code) return null
  return { system, code, display: code, active: true, context: null }
}

function comboLabel(item: TerminologyResult): string {
  return item.display && item.display !== item.code ? `${item.code} — ${item.display}` : item.code
}

export default function ProfessionalEditModal({ professional, onClose, onSaved }: Props) {
  const [cbo, setCbo] = useState<TerminologyResult | null>(initialResult(professional.cbo_code, 'cbo'))
  const [cnes, setCnes] = useState<TerminologyResult | null>(initialResult(professional.cnes_code, 'cnes'))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const updated = await apiFetch<Professional>(`/api/v1/professionals/${professional.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({
          cbo_code: cbo?.code ?? '',
          cnes_code: cnes?.code ?? '',
        }),
      })
      onSaved(updated)
    } catch {
      setError('Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-neu-ink">Editar profissional</h2>
            <p className="text-xs text-neu-inkMuted mt-0.5">{professional.user_name}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="text-slate-400 hover:text-slate-700 rounded-lg p-1"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          <div>
            <label className="block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide">
              CBO (Ocupação)
            </label>
            <RemoteCombobox<TerminologyResult>
              label="CBO"
              endpoint="/api/v1/terminology/cbo/"
              queryParam="q"
              value={cbo}
              getKey={(item) => item.code}
              getLabel={comboLabel}
              onChange={setCbo}
              placeholder="Buscar ocupação (CBO)..."
            />
          </div>

          <div>
            <label className="block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide">
              CNES (Estabelecimento)
            </label>
            <RemoteCombobox<TerminologyResult>
              label="CNES"
              endpoint="/api/v1/terminology/cnes/"
              queryParam="q"
              value={cnes}
              getKey={(item) => item.code}
              getLabel={comboLabel}
              onChange={setCnes}
              placeholder="Buscar estabelecimento (CNES)..."
            />
          </div>

          {error && <SectionState title="Erro ao salvar." detail={error} tone="critical" />}

          <div className="flex gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose} className="flex-1">
              Cancelar
            </Button>
            <Button type="submit" variant="primary" disabled={saving} className="flex-1">
              {saving ? 'Salvando...' : 'Salvar'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
