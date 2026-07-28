import { StatusBadge } from '@/components/shared'
import type { BadgeMeta } from '@/lib/operational-ui'

// One table row for a ProfessionalSettlement (repasse a terceiros).
//
// Lifecycle (maker-checker, enforced server-side):
//   draft ──approve──▶ approved ──pay──▶ paid
// The row exposes exactly the action legal for its current status: "Aprovar"
// for a draft, "Pagar" for an approved repasse, nothing once paid. The server
// also blocks the creator from approving their own repasse (segregation of
// duties) — surfaced as an action error, since the API never returns who
// created the record.

export type SettlementStatus = 'draft' | 'approved' | 'paid'

export interface Settlement {
  id: string
  professional: string
  professional_name: string
  competency: string
  gross_amount: string
  deductions: string
  net_amount: string
  status: SettlementStatus
  calculated_at: string | null
  paid_at: string | null
}

// Canonical status pill styling for repasses. Kept local to the billing area:
// `lib/operational-ui` is a shared surface we must not edit for this sprint.
export const SETTLEMENT_STATUS_META: Record<SettlementStatus, Pick<BadgeMeta, 'label' | 'badgeClass'>> = {
  draft: {
    label: 'Rascunho',
    badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
  },
  approved: {
    label: 'Aprovado',
    badgeClass: 'bg-neu-brand/10 text-neu-brand border-neu-brand/20',
  },
  paid: {
    label: 'Pago',
    badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20',
  },
}

const FALLBACK_META: Pick<BadgeMeta, 'label' | 'badgeClass'> = {
  label: 'Indefinido',
  badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
}

function fmtBRL(value: string | number | null): string {
  if (value == null) return '—'
  return Number(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

interface Props {
  settlement: Settlement
  onApprove?: (settlement: Settlement) => void
  onPay?: (settlement: Settlement) => void
}

export default function SettlementRow({ settlement, onApprove, onPay }: Props) {
  const meta = SETTLEMENT_STATUS_META[settlement.status] ?? {
    ...FALLBACK_META,
    label: settlement.status,
  }

  return (
    <tr className="border-b border-white hover:bg-neu-panelAlt">
      <td className="px-4 py-3 font-medium text-neu-ink">{settlement.professional_name || '—'}</td>
      <td className="px-4 py-3 font-mono text-xs text-neu-inkSoft">{settlement.competency || '—'}</td>
      <td className="px-4 py-3 text-right text-neu-inkSoft">{fmtBRL(settlement.gross_amount)}</td>
      <td className="px-4 py-3 text-right text-neu-inkSoft">{fmtBRL(settlement.deductions)}</td>
      <td className="px-4 py-3 text-right font-semibold text-neu-ink">{fmtBRL(settlement.net_amount)}</td>
      <td className="px-4 py-3">
        <StatusBadge meta={meta} />
      </td>
      <td className="px-4 py-3 text-right">
        {settlement.status === 'draft' && onApprove && (
          <button
            type="button"
            onClick={() => onApprove(settlement)}
            className="text-xs font-semibold text-neu-brand hover:underline"
          >
            Aprovar
          </button>
        )}
        {settlement.status === 'approved' && onPay && (
          <button
            type="button"
            onClick={() => onPay(settlement)}
            className="text-xs font-semibold text-neu-success hover:underline"
          >
            Pagar
          </button>
        )}
        {settlement.status === 'paid' && <span className="text-xs text-neu-inkMuted">—</span>}
      </td>
    </tr>
  )
}
