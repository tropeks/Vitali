'use client'

import { useCallback, useEffect, useState } from 'react'
import { Loader2, Receipt, RefreshCw } from 'lucide-react'
import { apiFetch, apiFetchWithStatus, ApiError } from '@/lib/api'
import { apiErrorMessage } from '@/lib/admin'
import { Button, SectionState } from '@/components/shared'
import TUSSCodeSearch, { type TUSSOption } from '@/components/billing/TUSSCodeSearch'
import { nowLocalInput, normalizeList, type Admission, type ListResponse } from './admission-types'

/** `InpatientFee` — mirrors `InpatientFeeSerializer` exactly (Onda2 2.1/2.2). */
export interface InpatientFee {
  id: string
  admission: string
  service_date: string
  tuss_code: number
  tuss_code_display: string
  description: string
  quantity: string
  unit: 'dia' | 'hora' | 'unidade'
  notes: string
  created_by: string | null
  created_by_name: string
  created_at: string
  updated_at: string
}

const UNIT_OPTIONS: Array<{ value: InpatientFee['unit']; label: string }> = [
  { value: 'unidade', label: 'Por unidade' },
  { value: 'dia', label: 'Por dia' },
  { value: 'hora', label: 'Por hora' },
]

const UNIT_LABELS: Record<string, string> = Object.fromEntries(
  UNIT_OPTIONS.map((option) => [option.value, option.label]),
)

/** Dict-shape 400 (`{"tuss_code": ["..."]}`) → first message per field. */
function extractFieldErrors(body: unknown): Record<string, string> {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return {}
  const errors: Record<string, string> = {}
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (Array.isArray(value) && value.length > 0) errors[key] = String(value[0])
    else if (typeof value === 'string') errors[key] = value
  }
  return errors
}

interface Props {
  patientId: string
  /**
   * Mirrors the backend's `CanRecordInpatientFee` (billing.write OR
   * emr.write) — the same gate `InpatientFeeViewSet` applies to both list and
   * create, so a single prop covers the whole panel. Deliberately includes
   * nursing (emr.write): the person who knows the incubator ran for 6 hours
   * is bedside, not in billing.
   */
  canManage: boolean
}

/**
 * Onda2 2.1/2.2 — lança taxas e gases medicinais na internação ativa do
 * paciente (`POST /billing/inpatient-fees/`), com a lista do que já foi
 * lançado logo acima do formulário para evitar duplicata por clique duplo.
 *
 * Vive na aba Internação do prontuário (ao lado de {@link AdmissionPanel}):
 * quem lança uma taxa de oxigênio está à beira do leito, no contexto da
 * internação — não numa tela de faturamento à parte.
 */
export default function InpatientFeePanel({ patientId, canManage }: Props) {
  const [admission, setAdmission] = useState<Admission | null>(null)
  const [admissionLoading, setAdmissionLoading] = useState(true)
  const [admissionError, setAdmissionError] = useState(false)

  const [fees, setFees] = useState<InpatientFee[]>([])
  const [feesLoading, setFeesLoading] = useState(false)

  const [tussCode, setTussCode] = useState<TUSSOption | null>(null)
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState<InpatientFee['unit']>('unidade')
  const [serviceDate, setServiceDate] = useState(() => nowLocalInput().slice(0, 10))
  const [notes, setNotes] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const loadFees = useCallback(async (admissionId: string) => {
    setFeesLoading(true)
    try {
      const data = await apiFetch<ListResponse<InpatientFee> | InpatientFee[]>(
        `/api/v1/billing/inpatient-fees/?admission=${admissionId}`,
      )
      setFees(normalizeList(data))
    } catch {
      setFees([])
    } finally {
      setFeesLoading(false)
    }
  }, [])

  const loadAdmission = useCallback(async () => {
    if (!patientId || !canManage) return
    setAdmissionLoading(true)
    setAdmissionError(false)
    try {
      const data = await apiFetch<ListResponse<Admission> | Admission[]>(
        `/api/v1/admissions/?patient=${patientId}&status=admitted`,
      )
      const active = normalizeList(data)[0] ?? null
      setAdmission(active)
      if (active) await loadFees(active.id)
    } catch {
      setAdmissionError(true)
    } finally {
      setAdmissionLoading(false)
    }
  }, [patientId, canManage, loadFees])

  useEffect(() => {
    loadAdmission()
  }, [loadAdmission])

  const canSubmit =
    !!tussCode && quantity.trim() !== '' && Number(quantity) > 0 && !submitting

  const submit = async () => {
    if (!admission || !tussCode) return
    setSubmitting(true)
    setFieldErrors({})
    setFormError(null)
    setNotice(null)
    try {
      const { data, status } = await apiFetchWithStatus<InpatientFee>(
        '/api/v1/billing/inpatient-fees/',
        {
          method: 'POST',
          body: JSON.stringify({
            admission: admission.id,
            tuss_code: tussCode.id,
            quantity: quantity.trim(),
            unit,
            service_date: serviceDate || undefined,
            notes: notes.trim(),
          }),
        },
      )
      if (status === 200) {
        setNotice(`Essa taxa já estava lançada (${data.tuss_code_display}) — nada foi duplicado.`)
      } else {
        setTussCode(null)
        setQuantity('')
        setUnit('unidade')
        setNotes('')
      }
      await loadFees(admission.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object' && !Array.isArray(err.body)) {
        setFieldErrors(extractFieldErrors(err.body))
      } else {
        setFormError(apiErrorMessage(err, 'Não foi possível lançar a taxa. Tente novamente.'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (!canManage) {
    return (
      <SectionState
        title="Sem acesso a taxas e gases medicinais"
        detail="Você não tem permissão para ver ou lançar taxas desta internação (billing.write ou emr.write)."
      />
    )
  }

  if (admissionLoading) {
    return (
      <SectionState
        title="Carregando taxas e gases medicinais..."
        detail="Buscando a internação ativa do paciente."
      />
    )
  }

  if (admissionError) {
    return (
      <SectionState
        title="Erro ao carregar taxas e gases medicinais"
        detail="Não foi possível carregar os dados. Tente novamente."
        tone="critical"
        action={
          <button
            onClick={loadAdmission}
            className="inline-flex items-center gap-2 text-xs font-semibold text-red-700 hover:underline"
          >
            <RefreshCw size={13} />
            Tentar novamente
          </button>
        }
      />
    )
  }

  if (!admission) {
    return (
      <SectionState
        title="Sem internação ativa"
        detail="Taxas e gases medicinais só podem ser lançados durante uma internação ativa."
      />
    )
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-neu-panel">
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
          <Receipt size={17} className="text-neu-brand" />
          <h3 className="text-sm font-semibold text-neu-ink">
            Taxas e gases medicinais lançados ({fees.length})
          </h3>
        </div>
        {feesLoading ? (
          <div className="flex items-center gap-2 px-4 py-4 text-sm text-neu-inkMuted">
            <Loader2 size={14} className="animate-spin" />
            Carregando lançamentos...
          </div>
        ) : fees.length === 0 ? (
          <p className="px-4 py-4 text-sm text-neu-inkMuted">
            Nenhuma taxa lançada nesta internação ainda.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100">
                <tr>
                  {['Data', 'TUSS', 'Quantidade', 'Unidade', 'Lançado por', 'Observação'].map(
                    (header) => (
                      <th
                        key={header}
                        className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
                      >
                        {header}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {fees.map((fee) => (
                  <tr key={fee.id}>
                    <td className="px-4 py-2 text-neu-ink">{fee.service_date}</td>
                    <td className="px-4 py-2 text-neu-ink">{fee.tuss_code_display}</td>
                    <td className="px-4 py-2 text-neu-ink">{fee.quantity}</td>
                    <td className="px-4 py-2 text-neu-inkSoft">
                      {UNIT_LABELS[fee.unit] ?? fee.unit}
                    </td>
                    <td className="px-4 py-2 text-neu-inkSoft">{fee.created_by_name || '—'}</td>
                    <td className="px-4 py-2 text-neu-inkSoft">{fee.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-neu-panel px-4 py-4">
        <h3 className="mb-3 text-sm font-semibold text-neu-ink">Lançar taxa / gás medicinal</h3>

        {notice && (
          <div className="mb-3 rounded-lg border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
            {notice}
          </div>
        )}
        {formError && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {formError}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-semibold text-neu-inkSoft">
              Código TUSS (tabela 18) *
            </label>
            <TUSSCodeSearch
              value={tussCode}
              onChange={setTussCode}
              placeholder="Buscar taxa, gás ou diária por código/descrição"
              disabled={submitting}
            />
            {fieldErrors.tuss_code && (
              <p className="mt-1 text-xs font-semibold text-red-700">{fieldErrors.tuss_code}</p>
            )}
          </div>

          <div>
            <label htmlFor="fee-quantity" className="mb-1 block text-xs font-semibold text-neu-inkSoft">
              Quantidade *
            </label>
            <input
              id="fee-quantity"
              type="number"
              min="0.01"
              step="0.01"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              disabled={submitting}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-neu-panel"
            />
            {fieldErrors.quantity && (
              <p className="mt-1 text-xs font-semibold text-red-700">{fieldErrors.quantity}</p>
            )}
          </div>

          <div>
            <label htmlFor="fee-unit" className="mb-1 block text-xs font-semibold text-neu-inkSoft">
              Unidade
            </label>
            <select
              id="fee-unit"
              value={unit}
              onChange={(e) => setUnit(e.target.value as InpatientFee['unit'])}
              disabled={submitting}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-neu-panel"
            >
              {UNIT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {fieldErrors.unit && (
              <p className="mt-1 text-xs font-semibold text-red-700">{fieldErrors.unit}</p>
            )}
          </div>

          <div>
            <label htmlFor="fee-date" className="mb-1 block text-xs font-semibold text-neu-inkSoft">
              Data do lançamento
            </label>
            <input
              id="fee-date"
              type="date"
              value={serviceDate}
              onChange={(e) => setServiceDate(e.target.value)}
              disabled={submitting}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-neu-panel"
            />
            {fieldErrors.service_date && (
              <p className="mt-1 text-xs font-semibold text-red-700">{fieldErrors.service_date}</p>
            )}
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="fee-notes" className="mb-1 block text-xs font-semibold text-neu-inkSoft">
              Observação (opcional)
            </label>
            <input
              id="fee-notes"
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={submitting}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-neu-panel"
            />
          </div>
        </div>

        <div className="mt-3">
          <Button
            type="button"
            variant="primary"
            onClick={() => void submit()}
            disabled={!canSubmit}
          >
            {submitting ? 'Lançando...' : 'Lançar taxa'}
          </Button>
        </div>
      </section>
    </div>
  )
}
