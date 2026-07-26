'use client'

import { useEffect, useState, type FormEvent } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { Button, SectionState } from '@/components/shared'
import type { Settlement } from './SettlementRow'

// Generate a new draft repasse. POST /api/v1/billing/settlements/ accepts only
// { professional, competency, deductions } — gross_amount/net_amount are
// recalculated server-side from the professional's signed encounters in that
// competency (status starts as 'draft'). The professional picker is loaded
// from the same governed endpoint used across the app.

interface ProfessionalOption {
  id: string
  user_name?: string
}

interface Props {
  onClose: () => void
  onCreated: (created: Settlement) => void
}

export default function SettlementCreateModal({ onClose, onCreated }: Props) {
  const [professionals, setProfessionals] = useState<ProfessionalOption[]>([])
  const [professional, setProfessional] = useState('')
  const [competency, setCompetency] = useState('')
  const [deductions, setDeductions] = useState('0')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    apiFetch<ProfessionalOption[] | { results: ProfessionalOption[] }>('/api/v1/professionals/')
      .then((data) => {
        if (!alive) return
        setProfessionals(Array.isArray(data) ? data : data.results ?? [])
      })
      .catch(() => {
        /* picker stays empty; the field validation blocks submit */
      })
    return () => {
      alive = false
    }
  }, [])

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const created = await apiFetch<Settlement>('/api/v1/billing/settlements/', {
        method: 'POST',
        body: JSON.stringify({
          professional,
          competency,
          deductions: deductions || '0',
        }),
      })
      onCreated(created)
    } catch {
      setError('Não foi possível gerar o repasse. Verifique os dados e tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h2 className="text-lg font-semibold text-neu-ink">Gerar repasse</h2>
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
              Prestador
            </label>
            <select
              required
              value={professional}
              onChange={(e) => setProfessional(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-neu-brand outline-none"
            >
              <option value="">Selecione o prestador...</option>
              {professionals.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.user_name || p.id}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide">
                Competência (AAAA-MM)
              </label>
              <input
                required
                type="month"
                value={competency}
                onChange={(e) => setCompetency(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-neu-brand outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold text-neu-inkSoft mb-1.5 uppercase tracking-wide">
                Deduções (R$)
              </label>
              <input
                type="number"
                min="0"
                step="0.01"
                value={deductions}
                onChange={(e) => setDeductions(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-neu-brand outline-none"
              />
            </div>
          </div>

          <p className="text-xs text-neu-inkMuted">
            O valor bruto e o líquido são calculados automaticamente a partir dos atendimentos
            assinados do prestador na competência.
          </p>

          {error && <SectionState title="Erro ao gerar repasse." detail={error} tone="critical" />}

          <div className="flex gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose} className="flex-1">
              Cancelar
            </Button>
            <Button type="submit" variant="primary" disabled={submitting} className="flex-1">
              {submitting ? 'Gerando...' : 'Gerar repasse'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
