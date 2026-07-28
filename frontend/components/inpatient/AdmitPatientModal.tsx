'use client'

import { useCallback, useEffect, useState } from 'react'
import { BedDouble, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  ADMISSION_SOURCE_OPTIONS,
  normalizeList,
  nowLocalInput,
  type BedOption,
  type ListResponse,
  type ProfessionalOption,
} from './admission-types'

interface Props {
  patientId: string
  onClose: () => void
  /** Called after a successful admit so the panel can refresh the active stay. */
  onAdmitted: () => void
}

/**
 * Admit modal — creates an inpatient stay (`POST /admissions/`, gated
 * `adt.admit`). Picks admitting + attending professional (`/professionals/`),
 * an admission source, a FREE bed (`/beds/?status=livre`) and the admission
 * datetime (default now). A 409 (bed occupied) surfaces as an inline error.
 */
export default function AdmitPatientModal({ patientId, onClose, onAdmitted }: Props) {
  const [beds, setBeds] = useState<BedOption[]>([])
  const [bedsLoading, setBedsLoading] = useState(true)
  const [bedId, setBedId] = useState('')
  const [admitting, setAdmitting] = useState<ProfessionalOption | null>(null)
  const [attending, setAttending] = useState<ProfessionalOption | null>(null)
  const [source, setSource] = useState('emergencia')
  const [datetime, setDatetime] = useState(() => nowLocalInput())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const loadBeds = useCallback(async () => {
    setBedsLoading(true)
    try {
      const data = await apiFetch<ListResponse<BedOption> | BedOption[]>(
        '/api/v1/beds/?status=livre',
      )
      setBeds(normalizeList(data))
    } catch {
      setBeds([])
    } finally {
      setBedsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadBeds()
  }, [loadBeds])

  const professionalLabel = (professional: ProfessionalOption) =>
    professional.user_name ||
    (professional.council_number ? `Registro ${professional.council_number}` : professional.id)

  const submit = async () => {
    if (!admitting || !attending || !bedId) {
      setError('Selecione profissional internador, responsável e um leito livre.')
      return
    }
    setSaving(true)
    setError('')
    const payload = {
      patient: patientId,
      admitting_professional: admitting.id,
      attending_professional: attending.id,
      bed: bedId,
      admission_source: source,
      admission_datetime: new Date(datetime).toISOString(),
    }
    try {
      await apiFetch('/api/v1/admissions/', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      onAdmitted()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Leito já ocupado. Escolha outro leito livre.')
        await loadBeds()
      } else {
        setError('Não foi possível registrar a internação. Revise os dados e tente novamente.')
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
      aria-label="Admitir paciente"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <BedDouble size={18} className="text-blue-600" />
            <h2 className="text-base font-semibold text-slate-900">Admitir paciente</h2>
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
          <RemoteCombobox<ProfessionalOption>
            label="Profissional internador"
            endpoint="/api/v1/professionals/"
            value={admitting}
            getKey={(item) => item.id}
            getLabel={professionalLabel}
            onChange={setAdmitting}
            placeholder="Buscar profissional..."
          />
          <RemoteCombobox<ProfessionalOption>
            label="Profissional responsável"
            endpoint="/api/v1/professionals/"
            value={attending}
            getKey={(item) => item.id}
            getLabel={professionalLabel}
            onChange={setAttending}
            placeholder="Buscar profissional..."
          />

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs font-semibold text-slate-600">
              Origem da internação
              <select
                value={source}
                onChange={(event) => setSource(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                {ADMISSION_SOURCE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-semibold text-slate-600">
              Data/hora da internação
              <input
                type="datetime-local"
                value={datetime}
                onChange={(event) => setDatetime(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <label className="block text-xs font-semibold text-slate-600">
            Leito livre
            <select
              value={bedId}
              onChange={(event) => setBedId(event.target.value)}
              disabled={bedsLoading}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:opacity-60"
            >
              <option value="">
                {bedsLoading
                  ? 'Carregando leitos...'
                  : beds.length === 0
                    ? 'Nenhum leito livre'
                    : 'Selecione um leito'}
              </option>
              {beds.map((bed) => (
                <option key={bed.id} value={bed.id}>
                  {bed.identifier}
                </option>
              ))}
            </select>
          </label>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {saving ? 'Admitindo...' : 'Confirmar internação'}
          </button>
        </div>
      </div>
    </div>
  )
}
