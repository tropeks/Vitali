'use client'

import { useState } from 'react'
import { Trash2, UserPlus, Users } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  TEAM_ROLE_OPTIONS,
  labelOf,
  type ProfessionalOption,
  type SurgicalTeamMemberEntry,
} from './surgery-case-types'

interface Props {
  caseId: string
  /** Current team of the case (from the timeline). */
  team: SurgicalTeamMemberEntry[]
  /** `surgery.manage` — gates the add form + remove buttons. */
  canManage: boolean
  /** Called after a successful add/remove so the panel can reload the timeline. */
  onChanged: () => void
}

/**
 * Equipe cirúrgica — the case's team members with roles. Reading is visible with
 * `surgery.read`; add (`POST /surgical-team/`) and remove (`DELETE
 * /surgical-team/{id}/`) are gated by `surgery.manage`. A duplicate
 * `(case, professional, role)` → 400, surfaced as a friendly inline message.
 */
export default function SurgeryTeamPanel({ caseId, team, canManage, onChanged }: Props) {
  const [role, setRole] = useState(TEAM_ROLE_OPTIONS[0].value)
  const [professional, setProfessional] = useState<ProfessionalOption | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const professionalLabel = (option: ProfessionalOption) =>
    option.user_name ||
    (option.council_number ? `Registro ${option.council_number}` : option.id)

  const add = async () => {
    if (!professional) {
      setError('Selecione um profissional para adicionar à equipe.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await apiFetch('/api/v1/surgical-team/', {
        method: 'POST',
        body: JSON.stringify({ case: caseId, professional: professional.id, role }),
      })
      setProfessional(null)
      onChanged()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError('Este profissional já ocupa essa função no caso.')
      } else {
        setError('Não foi possível adicionar o membro. Tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  const remove = async (member: SurgicalTeamMemberEntry) => {
    if (!confirm(`Remover ${member.professional_name ?? 'membro'} da equipe?`)) return
    try {
      await apiFetch(`/api/v1/surgical-team/${member.id}/`, { method: 'DELETE' })
      onChanged()
    } catch {
      setError('Não foi possível remover o membro. Tente novamente.')
    }
  }

  return (
    <div className="space-y-3">
      {team.length === 0 ? (
        <p className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
          Nenhum membro na equipe cirúrgica.
        </p>
      ) : (
        <ul className="space-y-2" aria-label="Equipe cirúrgica">
          {team.map((member) => (
            <li
              key={member.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">
                  {member.professional_name ?? 'Profissional'}
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {labelOf(TEAM_ROLE_OPTIONS, member.role)}
                </p>
              </div>
              {canManage && (
                <button
                  type="button"
                  onClick={() => remove(member)}
                  aria-label={`Remover ${member.professional_name ?? 'membro'}`}
                  className="inline-flex items-center gap-1 text-xs font-semibold text-red-600 hover:underline"
                >
                  <Trash2 size={14} />
                  Remover
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canManage && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="flex items-center gap-2">
            <Users size={15} className="text-blue-600" />
            <span className="text-sm font-semibold text-slate-900">Adicionar membro</span>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]">
            <RemoteCombobox<ProfessionalOption>
              label="Profissional"
              endpoint="/api/v1/professionals/"
              value={professional}
              getKey={(item) => item.id}
              getLabel={professionalLabel}
              onChange={setProfessional}
              placeholder="Buscar profissional..."
            />
            <label className="block text-xs font-semibold text-slate-600 sm:sr-only">
              Função
              <select
                aria-label="Função"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm sm:mt-0"
              >
                {TEAM_ROLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {error && <p className="mt-2 text-xs font-semibold text-red-700">{error}</p>}
          <button
            type="button"
            onClick={add}
            disabled={saving}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            <UserPlus size={15} />
            {saving ? 'Adicionando...' : 'Adicionar à equipe'}
          </button>
        </div>
      )}
    </div>
  )
}
