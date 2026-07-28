import { StatusBadge } from '@/components/shared'

/**
 * Canonical status pill for Contas a pagar (Payable.status).
 * Backend choices: planned / approved / paid / cancelled.
 */
export type PayableStatus = 'planned' | 'approved' | 'paid' | 'cancelled' | string

const META: Record<string, { label: string; badgeClass: string }> = {
  planned: { label: 'Prevista', badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20' },
  approved: { label: 'Aprovada', badgeClass: 'bg-neu-brand/10 text-neu-brand border-neu-brand/20' },
  paid: { label: 'Paga', badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20' },
  cancelled: { label: 'Cancelada', badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20' },
}

export function payableStatusMeta(status: string) {
  return META[status] ?? { label: status, badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20' }
}

export default function PayableStatusBadge({ status }: { status: PayableStatus }) {
  return <StatusBadge meta={payableStatusMeta(status)} />
}
