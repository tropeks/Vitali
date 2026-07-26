'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { Button, SectionState } from '@/components/shared'
import type { Settlement } from './SettlementRow'

// Confirmation modal for the two maker-checker transitions of a repasse:
//   'approve' → POST /api/v1/billing/settlements/{id}/approve/  (draft → approved)
//   'pay'     → POST /api/v1/billing/settlements/{id}/pay/      (approved → paid)
// Both are empty-body POSTs; the server locks, rechecks state, enforces
// segregation of duties (approver ≠ creator) and writes an audit row. Any 4xx
// (e.g. 403 maker == checker, 409 wrong state) is surfaced inline.

export type SettlementAction = 'approve' | 'pay'

interface Props {
  settlement: Settlement
  action: SettlementAction
  onClose: () => void
  onDone: (updated: Settlement) => void
}

const COPY: Record<
  SettlementAction,
  { title: string; confirm: string; verb: string; variant: 'primary' | 'danger' }
> = {
  approve: {
    title: 'Aprovar repasse',
    confirm: 'Confirmar aprovação',
    verb: 'aprovar',
    variant: 'primary',
  },
  pay: {
    title: 'Registrar pagamento',
    confirm: 'Confirmar pagamento',
    verb: 'pagar',
    variant: 'primary',
  },
}

function fmtBRL(value: string | number | null): string {
  if (value == null) return '—'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export default function SettlementDecideModal({ settlement, action, onClose, onDone }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const copy = COPY[action]

  const handleConfirm = async () => {
    setSubmitting(true)
    setError('')
    try {
      const updated = await apiFetch<Settlement>(
        `/api/v1/billing/settlements/${settlement.id}/${action}/`,
        { method: 'POST' }
      )
      onDone(updated)
    } catch {
      setError('Não foi possível concluir a ação. Verifique as permissões e tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-semibold text-neu-ink">{copy.title}</h2>
            <p className="text-xs text-neu-inkMuted mt-0.5">
              {settlement.professional_name} · {settlement.competency}
            </p>
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

        <div className="px-6 py-4 space-y-4">
          <p className="text-sm text-neu-inkSoft">
            Você está prestes a {copy.verb} o repasse líquido de{' '}
            <span className="font-semibold text-neu-ink">{fmtBRL(settlement.net_amount)}</span> para{' '}
            <span className="font-semibold text-neu-ink">{settlement.professional_name}</span>.
          </p>
          {action === 'approve' && (
            <p className="text-xs text-neu-inkMuted">
              Segregação de funções: o aprovador deve ser diferente de quem gerou o repasse.
            </p>
          )}

          {error && <SectionState title="Erro ao processar." detail={error} tone="critical" />}

          <div className="flex gap-3 pt-2">
            <Button type="button" variant="secondary" onClick={onClose} className="flex-1">
              Cancelar
            </Button>
            <Button
              type="button"
              variant={copy.variant}
              onClick={handleConfirm}
              disabled={submitting}
              className="flex-1"
            >
              {submitting ? 'Processando...' : copy.confirm}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
