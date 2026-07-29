'use client'

import { useCallback, useEffect, useState } from 'react'
import { ClipboardPlus, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  apiErrorDetail,
  normalizeList,
  URGENCIA_OPTIONS,
  type BloodComponentDTO,
  type EncounterOption,
  type ListResponse,
  type PatientOption,
  type ProfessionalOption,
  type Urgencia,
} from './bloodbank-types'

interface NewTransfusionRequestModalProps {
  onClose: () => void
  onCreated: () => void
}

function encounterLabel(enc: EncounterOption): string {
  const parts = [enc.encounter_type, enc.status].filter(Boolean)
  const head = parts.length ? parts.join(' · ') : 'Atendimento'
  return `${head} #${enc.id.slice(0, 8)}`
}

/**
 * Nova requisição transfusional (hemoterapia.request) — the requesting médico's
 * order via POST /api/v1/transfusion-requests/. Requires a patient, one order
 * parent (here an encounter, fetched for the chosen patient), the requested
 * hemocomponente, quantidade, indicação, urgência and the requester
 * (professional). The backend sets status=solicitada.
 */
export default function NewTransfusionRequestModal({
  onClose,
  onCreated,
}: NewTransfusionRequestModalProps) {
  const [patient, setPatient] = useState<PatientOption | null>(null)
  const [encounters, setEncounters] = useState<EncounterOption[]>([])
  const [encounterId, setEncounterId] = useState('')
  const [component, setComponent] = useState<BloodComponentDTO | null>(null)
  const [requester, setRequester] = useState<ProfessionalOption | null>(null)
  const [quantidade, setQuantidade] = useState('1')
  const [indicacao, setIndicacao] = useState('')
  const [cid, setCid] = useState('')
  const [urgencia, setUrgencia] = useState<Urgencia>('rotina')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadEncounters = useCallback(async (patientId: string) => {
    try {
      const data = await apiFetch<ListResponse<EncounterOption> | EncounterOption[]>(
        `/api/v1/encounters/?patient=${patientId}`
      )
      setEncounters(normalizeList(data))
    } catch {
      setEncounters([])
    }
  }, [])

  useEffect(() => {
    setEncounterId('')
    if (patient) void loadEncounters(patient.id)
    else setEncounters([])
  }, [patient, loadEncounters])

  const professionalLabel = (p: ProfessionalOption) =>
    p.user_name || (p.council_number ? `Registro ${p.council_number}` : p.id)

  async function submit() {
    if (!patient) {
      setError('Selecione o paciente.')
      return
    }
    if (!encounterId) {
      setError('Selecione o atendimento vinculado à requisição.')
      return
    }
    if (!component) {
      setError('Selecione o hemocomponente.')
      return
    }
    if (!requester) {
      setError('Selecione o profissional solicitante.')
      return
    }
    if (!indicacao.trim()) {
      setError('Informe a indicação clínica.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch('/api/v1/transfusion-requests/', {
        method: 'POST',
        body: JSON.stringify({
          patient: patient.id,
          encounter: encounterId,
          component: component.id,
          quantidade: Number(quantidade) || 1,
          indicacao: indicacao.trim(),
          cid: cid.trim(),
          urgencia,
          requester: requester.id,
        }),
      })
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
        setError(apiErrorDetail(err.body, 'Não foi possível criar a requisição — revise os dados.'))
        return
      }
      setError('Não foi possível criar a requisição. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Nova requisição transfusional"
    >
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-neu-modal">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <ClipboardPlus size={18} className="text-neu-brand" aria-hidden />
            <h2 className="text-base font-semibold text-neu-ink">Nova requisição transfusional</h2>
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

        <div className="space-y-3 px-5 py-4">
          <div className="text-xs font-semibold text-neu-inkSoft">
            Paciente
            <div className="mt-1">
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
          </div>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Atendimento
            <select
              aria-label="Atendimento"
              value={encounterId}
              onChange={(e) => setEncounterId(e.target.value)}
              disabled={!patient}
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink disabled:opacity-50"
            >
              <option value="">
                {!patient
                  ? 'Selecione o paciente primeiro'
                  : encounters.length === 0
                    ? 'Nenhum atendimento encontrado'
                    : 'Selecione o atendimento...'}
              </option>
              {encounters.map((enc) => (
                <option key={enc.id} value={enc.id}>
                  {encounterLabel(enc)}
                </option>
              ))}
            </select>
          </label>

          <div className="text-xs font-semibold text-neu-inkSoft">
            Hemocomponente
            <div className="mt-1">
              <RemoteCombobox<BloodComponentDTO>
                label="Hemocomponente"
                endpoint="/api/v1/blood-components/"
                queryParam="q"
                value={component}
                getKey={(item) => String(item.id)}
                getLabel={(item) => `${item.code} — ${item.display}`}
                onChange={setComponent}
                placeholder="Buscar hemocomponente..."
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Quantidade (un.)
              <input
                type="number"
                min={1}
                aria-label="Quantidade"
                value={quantidade}
                onChange={(e) => setQuantidade(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              />
            </label>
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Urgência
              <select
                aria-label="Urgência"
                value={urgencia}
                onChange={(e) => setUrgencia(e.target.value as Urgencia)}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              >
                {URGENCIA_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="text-xs font-semibold text-neu-inkSoft">
            Solicitante
            <div className="mt-1">
              <RemoteCombobox<ProfessionalOption>
                label="Solicitante"
                endpoint="/api/v1/professionals/"
                value={requester}
                getKey={(item) => item.id}
                getLabel={professionalLabel}
                onChange={setRequester}
                placeholder="Buscar profissional..."
              />
            </div>
          </div>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Indicação clínica
            <textarea
              aria-label="Indicação clínica"
              value={indicacao}
              onChange={(e) => setIndicacao(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
            />
          </label>

          <label className="block text-xs font-semibold text-neu-inkSoft">
            CID (opcional)
            <input
              aria-label="CID"
              value={cid}
              onChange={(e) => setCid(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
            />
          </label>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-neu-inkSoft hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? 'Criando...' : 'Criar requisição'}
          </button>
        </div>
      </div>
    </div>
  )
}
