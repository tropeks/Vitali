import { Badge, StatusBadge } from '@/components/shared'
import { getActivenessMeta } from '@/lib/operational-ui'

// Single table row for a Professional record.
// Council display format: "<council_type> <council_number>/<council_state>"
// e.g. "CRM 12345/SP". Status badge resolves through the canonical derived-
// boolean adapter so the activeness pill is the same on every screen.
//
// cbo_unmatched/cnes_unmatched are read-only server flags (A1): true when the
// stored cbo_code/cnes_code did NOT reconcile to a governed catalog entry —
// surfaced here as a "não reconciliado" warning badge next to the code.

export interface Professional {
  id: string
  user: string
  user_name: string
  user_email: string
  council_type: string
  council_type_display: string
  council_number: string
  council_state: string
  specialty: string | null
  cbo_code: string | null
  cnes_code: string | null
  cbo_unmatched: boolean
  cnes_unmatched: boolean
  is_active: boolean
  created_at: string
}

interface Props {
  professional: Professional
  onEdit?: (professional: Professional) => void
}

function CodeCell({ code, unmatched }: { code: string | null; unmatched: boolean }) {
  if (!code) return <>—</>
  return (
    <div className="flex items-center gap-1.5">
      <span>{code}</span>
      {unmatched && <Badge variant="warning">não reconciliado</Badge>}
    </div>
  )
}

export default function ProfessionalRow({ professional, onEdit }: Props) {
  const councilDisplay =
    professional.council_type && professional.council_number && professional.council_state
      ? `${professional.council_type} ${professional.council_number}/${professional.council_state}`
      : '—'

  return (
    <tr className="border-b border-white hover:bg-neu-panelAlt">
      <td className="px-4 py-3 font-medium text-neu-ink">{professional.user_name || '—'}</td>
      <td className="px-4 py-3 text-neu-inkSoft">{professional.user_email || '—'}</td>
      <td className="px-4 py-3 font-mono text-xs text-neu-inkSoft">{councilDisplay}</td>
      <td className="px-4 py-3 text-neu-inkSoft">{professional.specialty || '—'}</td>
      <td className="px-4 py-3 font-mono text-xs text-neu-inkSoft">
        <CodeCell code={professional.cbo_code} unmatched={professional.cbo_unmatched} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-neu-inkSoft">
        <CodeCell code={professional.cnes_code} unmatched={professional.cnes_unmatched} />
      </td>
      <td className="px-4 py-3">
        <StatusBadge meta={getActivenessMeta(professional.is_active)} />
      </td>
      <td className="px-4 py-3">
        {onEdit && (
          <button
            type="button"
            onClick={() => onEdit(professional)}
            className="text-xs font-semibold text-neu-brand hover:underline"
          >
            Editar
          </button>
        )}
      </td>
    </tr>
  )
}
