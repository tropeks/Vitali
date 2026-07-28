'use client'

import { useCallback, useEffect, useState } from 'react'
import { LogOut, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import {
  ADMISSION_SOURCE_OPTIONS,
  DISPOSITION_OPTIONS,
  normalizeList,
  professionalLabel,
  type BedOption,
  type ListResponse,
  type ProfessionalOption,
} from './ps-board-types'

interface DispositionModalProps {
  boletimId: string
  patientName: string
  onClose: () => void
  /** Called after a successful desfecho so the board can refetch. */
  onClosed: () => void
}

/**
 * Desfecho / encerramento (emergency.manage) — closes a boletim via
 * POST /emergency-encounters/{id}/close/ {disposition, …}. When disposition is
 * `internacao` and a FREE bed (`/beds/?status=livre`) is chosen, the internação
 * bridge (adt.admit) needs admitting + attending professional + origem, and the
 * close creates the Admission in the same transaction. A 409 (leito ocupado /
 * transição inválida) surfaces as a friendly inline error.
 */
export default function DispositionModal({
  boletimId,
  patientName,
  onClose,
  onClosed,
}: DispositionModalProps) {
  const [disposition, setDisposition] = useState(DISPOSITION_OPTIONS[0].value)
  const [reason, setReason] = useState('')

  // Internação bridge fields
  const [beds, setBeds] = useState<BedOption[]>([])
  const [bedsLoading, setBedsLoading] = useState(false)
  const [bedId, setBedId] = useState('')
  const [admitting, setAdmitting] = useState<ProfessionalOption | null>(null)
  const [attending, setAttending] = useState<ProfessionalOption | null>(null)
  const [source, setSource] = useState(ADMISSION_SOURCE_OPTIONS[0].value)

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const isInternacao = disposition === 'internacao'

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
    if (isInternacao && beds.length === 0) {
      loadBeds()
    }
  }, [isInternacao, beds.length, loadBeds])

  async function submit() {
    // Backend requires both professionals when interning WITH a bed.
    if (isInternacao && bedId && (!admitting || !attending)) {
      setError('Ao internar com leito, selecione profissional internador e responsável.')
      return
    }
    setSaving(true)
    setError('')
    const body: Record<string, string> = { disposition }
    if (reason.trim()) body.reason = reason.trim()
    if (isInternacao && bedId) {
      body.bed = bedId
      body.admission_source = source
      if (admitting) body.admitting_professional = admitting.id
      if (attending) body.attending_professional = attending.id
    }
    try {
      await apiFetch(`/api/v1/emergency-encounters/${boletimId}/close/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onClosed()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('Leito ocupado ou transição inválida. Escolha outro leito ou revise o desfecho.')
        if (isInternacao) await loadBeds()
        return
      }
      setError('Não foi possível registrar o desfecho. Revise os dados e tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Registrar desfecho"
    >
      <div className="w-full max-w-lg rounded-xl border border-white bg-neu-panel shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <LogOut size={18} className="text-neu-brand" aria-hidden />
            <div>
              <h2 className="text-base font-semibold text-neu-ink">Registrar desfecho</h2>
              <p className="text-xs text-neu-inkMuted">{patientName}</p>
            </div>
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
          <label className="block text-xs font-semibold text-neu-inkSoft">
            Desfecho
            <select
              aria-label="Desfecho"
              value={disposition}
              onChange={(e) => setDisposition(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink"
            >
              {DISPOSITION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          {isInternacao && (
            <div className="space-y-4 rounded-lg border border-slate-200 bg-neu-panel/60 p-3">
              <p className="text-xs font-semibold text-neu-inkMuted">
                Internação — escolha um leito livre para acionar a admissão (ADT). Sem leito, o
                boletim encerra como internação para admitir depois.
              </p>
              <label className="block text-xs font-semibold text-neu-inkSoft">
                Leito livre
                <select
                  aria-label="Leito livre"
                  value={bedId}
                  onChange={(e) => setBedId(e.target.value)}
                  disabled={bedsLoading}
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink disabled:opacity-60"
                >
                  <option value="">
                    {bedsLoading
                      ? 'Carregando leitos...'
                      : beds.length === 0
                        ? 'Nenhum leito livre — admitir depois'
                        : 'Selecione um leito (opcional)'}
                  </option>
                  {beds.map((bed) => (
                    <option key={bed.id} value={bed.id}>
                      {bed.identifier}
                    </option>
                  ))}
                </select>
              </label>

              {bedId && (
                <>
                  <div>
                    <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">
                      Profissional internador
                    </span>
                    <RemoteCombobox<ProfessionalOption>
                      label="Profissional internador"
                      endpoint="/api/v1/professionals/"
                      value={admitting}
                      getKey={(item) => item.id}
                      getLabel={professionalLabel}
                      onChange={setAdmitting}
                      placeholder="Buscar profissional..."
                    />
                  </div>
                  <div>
                    <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">
                      Profissional responsável
                    </span>
                    <RemoteCombobox<ProfessionalOption>
                      label="Profissional responsável"
                      endpoint="/api/v1/professionals/"
                      value={attending}
                      getKey={(item) => item.id}
                      getLabel={professionalLabel}
                      onChange={setAttending}
                      placeholder="Buscar profissional..."
                    />
                  </div>
                  <label className="block text-xs font-semibold text-neu-inkSoft">
                    Origem da internação
                    <select
                      aria-label="Origem da internação"
                      value={source}
                      onChange={(e) => setSource(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink"
                    >
                      {ADMISSION_SOURCE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
            </div>
          )}

          <label className="block text-xs font-semibold text-neu-inkSoft">
            Motivo / observações (opcional)
            <textarea
              aria-label="Motivo do desfecho"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-neu-input px-3 py-2 text-sm text-neu-ink"
              placeholder="Observações sobre o desfecho..."
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
            {saving ? 'Registrando...' : 'Confirmar desfecho'}
          </button>
        </div>
      </div>
    </div>
  )
}
