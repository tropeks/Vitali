// ─── ProfessionalRow ─────────────────────────────────────────────────────────
// Single table row for a Professional record.
// Council display format: "<council_type> <council_number>/<council_state>"
// e.g. "CRM 12345/SP"

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
  is_active: boolean
  created_at: string
}

interface Props {
  professional: Professional
}

export default function ProfessionalRow({ professional }: Props) {
  const councilDisplay =
    professional.council_type && professional.council_number && professional.council_state
      ? `${professional.council_type} ${professional.council_number}/${professional.council_state}`
      : '—'

  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50">
      <td className="px-4 py-3 font-medium text-slate-900">{professional.user_name || '—'}</td>
      <td className="px-4 py-3 text-slate-600">{professional.user_email || '—'}</td>
      <td className="px-4 py-3 text-slate-600">{councilDisplay}</td>
      <td className="px-4 py-3 text-slate-600">{professional.specialty || '—'}</td>
      <td className="px-4 py-3">
        {professional.is_active ? (
          <span className="bg-green-100 text-green-700 px-2 py-0.5 rounded-full text-xs">
            Ativo
          </span>
        ) : (
          <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full text-xs">
            Inativo
          </span>
        )}
      </td>
    </tr>
  )
}
