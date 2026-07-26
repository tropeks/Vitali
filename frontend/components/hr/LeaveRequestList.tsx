'use client'

import { StatusBadge } from '@/components/shared'
import SectionState from '@/components/shared/SectionState'
import type { LeaveRequest } from '@/app/(dashboard)/rh/afastamentos/page'

/**
 * Read-only table of leave/absence requests with status pills and a
 * maker-checker decide action. The requester of a pending request never sees
 * the decide button (server also blocks self-approval); everyone else sees
 * "Decidir" for pending requests only.
 */

// Local canonical status meta — StatusBadge only needs { label, badgeClass }.
// Colours mirror the neu-token recipes used by EMPLOYMENT_STATUS_META.
const LEAVE_STATUS_META: Record<string, { label: string; badgeClass: string }> = {
  pending: {
    label: 'Pendente',
    badgeClass: 'bg-neu-warning/10 text-neu-warning border-neu-warning/20',
  },
  approved: {
    label: 'Aprovado',
    badgeClass: 'bg-neu-success/10 text-neu-success border-neu-success/20',
  },
  rejected: {
    label: 'Rejeitado',
    badgeClass: 'bg-neu-danger/10 text-neu-danger border-neu-danger/20',
  },
}

const FALLBACK_META = {
  label: '—',
  badgeClass: 'bg-neu-inkMuted/10 text-neu-inkSoft border-neu-inkMuted/20',
}

const LEAVE_TYPE_LABELS: Record<string, string> = {
  ferias: 'Férias',
  licenca_medica: 'Licença médica',
  licenca_maternidade: 'Licença maternidade',
  abono: 'Abono',
  outro: 'Outro',
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString('pt-BR')
  } catch {
    return dateStr
  }
}

export interface LeaveRequestListProps {
  requests: LeaveRequest[]
  currentUserId: string | null
  onDecide: (request: LeaveRequest) => void
}

export default function LeaveRequestList({
  requests,
  currentUserId,
  onDecide,
}: LeaveRequestListProps) {
  if (requests.length === 0) {
    return (
      <SectionState
        title="Nenhuma solicitação de afastamento ainda."
        detail="Use o botão Solicitar afastamento para registrar férias ou licenças da equipe."
      />
    )
  }

  return (
    <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead>
          <tr className="border-b border-slate-100 bg-neu-panel">
            {['Funcionário', 'Tipo', 'Período', 'Solicitante', 'Status', 'Ações'].map((h) => (
              <th
                key={h}
                className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {requests.map((req) => {
            const isOwn = currentUserId != null && req.requested_by === currentUserId
            const isPending = req.status === 'pending'
            const meta = LEAVE_STATUS_META[req.status] ?? FALLBACK_META
            return (
              <tr key={req.id} className="hover:bg-neu-panelAlt transition-colors align-top">
                <td className="px-4 py-3 font-medium text-neu-ink">
                  {req.employee_name ?? req.employee ?? '—'}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  {req.leave_type_display ?? LEAVE_TYPE_LABELS[req.leave_type] ?? req.leave_type}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft whitespace-nowrap">
                  {formatDate(req.start_date)} — {formatDate(req.end_date)}
                </td>
                <td className="px-4 py-3 text-neu-inkSoft">
                  {req.requested_by_name ?? '—'}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge meta={meta} />
                </td>
                <td className="px-4 py-3">
                  {isPending && isOwn && (
                    <span className="text-xs text-neu-inkMuted">
                      Você não pode decidir sua própria solicitação.
                    </span>
                  )}
                  {isPending && !isOwn && (
                    <button
                      onClick={() => onDecide(req)}
                      className="text-neu-brand hover:underline text-xs font-semibold"
                    >
                      Decidir
                    </button>
                  )}
                  {!isPending && (
                    <span className="text-xs text-neu-inkMuted">
                      {req.approval?.notes ? req.approval.notes : '—'}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
