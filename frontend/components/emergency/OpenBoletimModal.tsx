'use client'

import { useState } from 'react'
import { Siren, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  MODE_OF_ARRIVAL_OPTIONS,
  type PatientOption,
} from './ps-board-types'

interface OpenBoletimModalProps {
  onClose: () => void
  /** Called after a successful open so the board can refetch. */
  onOpened: () => void
}

/**
 * Abrir boletim (emergency.manage) — opens a PS boletim de atendimento via
 * POST /api/v1/emergency-encounters/ {patient, mode_of_arrival, chief_complaint}.
 * Picks the patient (`/patients/?search=`), the meio de chegada e a queixa. The
 * boletim starts `aguardando_classificacao` (triagem is a separate step).
 */
export default function OpenBoletimModal({ onClose, onOpened }: OpenBoletimModalProps) {
  const [patient, setPatient] = useState<PatientOption | null>(null)
  const [mode, setMode] = useState(MODE_OF_ARRIVAL_OPTIONS[0].value)
  const [chiefComplaint, setChiefComplaint] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!patient) {
      setError('Selecione o paciente.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await apiFetch('/api/v1/emergency-encounters/', {
        method: 'POST',
        body: JSON.stringify({
          patient: patient.id,
          mode_of_arrival: mode,
          chief_complaint: chiefComplaint.trim(),
        }),
      })
      onOpened()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Não foi possível abrir o boletim (conflito). Tente novamente.')
      } else {
        setError('Não foi possível abrir o boletim. Revise os dados e tente novamente.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Abrir boletim"
    >
      <div className="w-full max-w-lg rounded-xl border border-white bg-neu-panel shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <Siren size={18} className="text-red-600" aria-hidden />
            <h2 className="text-base font-semibold text-neu-ink">Abrir boletim</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div>
            <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">Paciente</span>
            <RemoteCombobox<PatientOption>
              label="Paciente"
              endpoint="/api/v1/patients/"
              value={patient}
              getKey={(item) => item.id}
              getLabel={(item) => item.full_name}
              onChange={setPatient}
              placeholder="Buscar paciente..."
            />
          </div>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Meio de chegada
            <select
              aria-label="Meio de chegada"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink"
            >
              {MODE_OF_ARRIVAL_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Queixa principal
            <textarea
              aria-label="Queixa principal"
              value={chiefComplaint}
              onChange={(e) => setChiefComplaint(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink"
              placeholder="Ex.: dor torácica há 2h..."
            />
          </label>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-neu-inkSoft hover:bg-neu-panel"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Abrindo...' : 'Abrir boletim'}
          </button>
        </div>
      </div>
    </div>
  )
}
