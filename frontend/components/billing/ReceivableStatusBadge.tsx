import { StatusBadge } from '@/components/shared'

/**
 * Canonical status pill for Contas a receber (AccountsReceivable.status).
 * Backend choices: expected / billed / partial / received / overdue / contested.
 */
export type ReceivableStatus =
  | 'expected'
  | 'billed'
  | 'partial'
  | 'received'
  | 'overdue'
  | 'contested'
  | string

const META: Record<string, { label: string; badgeClass: string }> = {
  expected: { label: 'Previsto', badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20' },
  billed: { label: 'Faturado', badgeClass: 'bg-neu-brand/10 text-neu-brand border-neu-brand/20' },
  partial: { label: 'Parcial', badgeClass: 'bg-neu-warning/10 text-neu-warning border-neu-warning/20' },
  received: { label: 'Recebido', badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20' },
  overdue: { label: 'Vencido', badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20' },
  contested: { label: 'Contestado', badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20' },
}

export function receivableStatusMeta(status: string) {
  return META[status] ?? { label: status, badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20' }
}

export default function ReceivableStatusBadge({ status }: { status: ReceivableStatus }) {
  return <StatusBadge meta={receivableStatusMeta(status)} />
}
