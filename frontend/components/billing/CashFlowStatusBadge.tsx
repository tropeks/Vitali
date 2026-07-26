import { StatusBadge } from '@/components/shared'

/**
 * Canonical status pill for Tesouraria / fluxo de caixa (CashFlowEntry.status).
 * Backend choices: forecast / realized / cancelled.
 */
export type CashFlowStatus = 'forecast' | 'realized' | 'cancelled' | string

const META: Record<string, { label: string; badgeClass: string }> = {
  forecast: { label: 'Previsto', badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20' },
  realized: { label: 'Realizado', badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20' },
  cancelled: { label: 'Cancelado', badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20' },
}

export function cashFlowStatusMeta(status: string) {
  return META[status] ?? { label: status, badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20' }
}

export default function CashFlowStatusBadge({ status }: { status: CashFlowStatus }) {
  return <StatusBadge meta={cashFlowStatusMeta(status)} />
}
