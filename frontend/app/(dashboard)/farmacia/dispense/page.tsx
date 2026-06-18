'use client'

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  PackageSearch,
  Pill,
  RotateCcw,
  Search,
  ShieldAlert,
} from 'lucide-react'
import { getAccessToken } from '@/lib/auth'
import { ApiError } from '@/lib/api'
import { isDoseSafetyBlock, type DoseSafetyBlock } from '@/lib/dose-safety'
import { PRESCRIPTION_STATUS_META, resolveBadgeMeta } from '@/lib/operational-ui'
import { PageShell, ReadinessPanel, StatusBadge } from '@/components/shared'
import { DoseSafetyModal } from '@/components/prescriptions/DoseSafetyModal'

function extractError(err: any): string {
  if (typeof err === 'string') return err
  if (err?.detail) return String(err.detail)
  const firstVal = Object.values(err ?? {})[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao dispensar. Tente novamente.'
}

type ApiList<T> = T[] | { results?: T[] }

type Patient = {
  id: string
  full_name: string
  medical_record_number?: string
  birth_date?: string
}

type RxItem = {
  id: string
  drug: string
  drug_name: string
  drug_generic_name: string
  drug_is_controlled: boolean
  quantity: string
  unit_of_measure: string
  dosage_instructions: string
}

type Prescription = {
  id: string
  patient?: string
  patient_name?: string
  patient_mrn?: string
  prescriber_name: string
  status: string
  status_display?: string
  is_signed: boolean
  created_at: string
  items: RxItem[]
}

type Lot = {
  id: string
  lot_number: string
  expiry_date: string | null
  quantity: string
  location?: string
  is_expired?: boolean
  is_low_stock?: boolean
}

type AvailabilityResult = {
  available_lots?: Lot[]
  total?: number
}

type DispenseResult = {
  id: string
  total_quantity: string
  lots: {
    stock_item: string
    lot_number?: string
    expiry_date?: string | null
    quantity: string
  }[]
}

function listFromResponse<T>(data: ApiList<T>): T[] {
  return Array.isArray(data) ? data : data.results ?? []
}

async function apiGet<T>(path: string): Promise<T> {
  const token = getAccessToken()
  if (!token) throw new Error('Sessão expirada')
  const response = await fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error(`Falha ${response.status}`)
  return response.json()
}

function parseQty(value: string | number | null | undefined) {
  const parsed = Number.parseFloat(String(value ?? 0))
  return Number.isFinite(parsed) ? parsed : 0
}

function formatQty(value: string | number | null | undefined) {
  return parseQty(value).toLocaleString('pt-BR', { maximumFractionDigits: 3 })
}

function formatDate(value?: string | null) {
  return value ? value.slice(0, 10) : '-'
}

function patientMrn(patient: Patient | null, rx?: Prescription | null) {
  return patient?.medical_record_number ?? rx?.patient_mrn ?? 'MRN pendente'
}

function itemStatus(item: RxItem, selectedItem: RxItem | null) {
  if (selectedItem?.id === item.id) return 'Em fechamento'
  if (item.drug_is_controlled) return 'Controlado'
  return 'Liberado'
}

export default function DispensePage() {
  const searchParams = useSearchParams()
  const prefillPatientId = searchParams.get('patient')

  const [patientQuery, setPatientQuery] = useState('')
  const [patients, setPatients] = useState<Patient[]>([])
  const [loadingPatients, setLoadingPatients] = useState(false)
  const [loadingPrefill, setLoadingPrefill] = useState(false)
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null)
  const [prescriptions, setPrescriptions] = useState<Prescription[]>([])
  const [loadingRx, setLoadingRx] = useState(false)
  const [selectedRx, setSelectedRx] = useState<Prescription | null>(null)
  const [selectedItem, setSelectedItem] = useState<RxItem | null>(null)
  const [quantity, setQuantity] = useState('')
  const [notes, setNotes] = useState('')
  const [lots, setLots] = useState<Lot[]>([])
  const [loadingLots, setLoadingLots] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<DispenseResult | null>(null)
  const [doseBlock, setDoseBlock] = useState<DoseSafetyBlock | null>(null)

  const searchPatientsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefillLoadedRef = useRef(false)

  const searchPatientsNow = useCallback(async (q: string) => {
    if (!q.trim()) {
      setPatients([])
      return
    }
    setLoadingPatients(true)
    try {
      const data = await apiGet<ApiList<Patient>>(`/patients/?search=${encodeURIComponent(q)}`)
      setPatients(listFromResponse(data))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível buscar pacientes.')
    } finally {
      setLoadingPatients(false)
    }
  }, [])

  const searchPatients = useCallback((q: string) => {
    if (searchPatientsTimerRef.current) clearTimeout(searchPatientsTimerRef.current)
    searchPatientsTimerRef.current = setTimeout(() => searchPatientsNow(q), 300)
  }, [searchPatientsNow])

  const loadPrescriptions = useCallback(async (patientId: string) => {
    setLoadingRx(true)
    try {
      const [signedData, partialData] = await Promise.all([
        apiGet<ApiList<Prescription>>(`/prescriptions/?patient=${patientId}&status=signed`),
        apiGet<ApiList<Prescription>>(`/prescriptions/?patient=${patientId}&status=partially_dispensed`),
      ])
      const merged = [...listFromResponse(signedData), ...listFromResponse(partialData)]
      setPrescriptions(merged)
      return merged
    } catch (err) {
      setPrescriptions([])
      setError(err instanceof Error ? err.message : 'Não foi possível carregar prescrições.')
      return []
    } finally {
      setLoadingRx(false)
    }
  }, [])

  const selectPatient = useCallback(async (patient: Patient) => {
    setSelectedPatient(patient)
    setPatients([])
    setPatientQuery(patient.full_name)
    setSelectedRx(null)
    setSelectedItem(null)
    setQuantity('')
    setNotes('')
    setLots([])
    setResult(null)
    setError('')
    await loadPrescriptions(patient.id)
  }, [loadPrescriptions])

  useEffect(() => {
    if (!prefillPatientId || prefillLoadedRef.current) return
    prefillLoadedRef.current = true
    let active = true
    setLoadingPrefill(true)
    apiGet<Patient>(`/patients/${prefillPatientId}/`)
      .then(async (patient) => {
        if (!active) return
        await selectPatient(patient)
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : 'Não foi possível abrir o paciente informado.')
      })
      .finally(() => {
        if (active) setLoadingPrefill(false)
      })
    return () => {
      active = false
    }
  }, [prefillPatientId, selectPatient])

  const loadLots = useCallback(async (drugId: string) => {
    if (!drugId) {
      setLots([])
      return
    }
    setLoadingLots(true)
    try {
      const data = await apiGet<AvailabilityResult>(`/pharmacy/stock/availability/?drug=${drugId}`)
      setLots(data.available_lots ?? [])
    } catch (err) {
      setLots([])
      setError(err instanceof Error ? err.message : 'Não foi possível verificar estoque FEFO.')
    } finally {
      setLoadingLots(false)
    }
  }, [])

  const selectItem = (rx: Prescription, item: RxItem) => {
    setSelectedRx(rx)
    setSelectedItem(item)
    setQuantity(item.quantity)
    setNotes('')
    setLots([])
    setError('')
    setResult(null)
    loadLots(item.drug)
  }

  const reset = () => {
    setPatientQuery('')
    setPatients([])
    setSelectedPatient(null)
    setPrescriptions([])
    setSelectedRx(null)
    setSelectedItem(null)
    setQuantity('')
    setNotes('')
    setLots([])
    setError('')
    setResult(null)
  }

  const requestedQty = parseQty(quantity)
  const prescribedQty = parseQty(selectedItem?.quantity)
  const availableQty = lots.reduce((sum, lot) => sum + parseQty(lot.quantity), 0)
  const totalItems = prescriptions.reduce((sum, rx) => sum + rx.items.length, 0)
  const controlledItems = prescriptions.reduce(
    (sum, rx) => sum + rx.items.filter((item) => item.drug_is_controlled).length,
    0,
  )
  const selectedControlled = Boolean(selectedItem?.drug_is_controlled)

  const blockers = useMemo(() => {
    const current: string[] = []
    if (!selectedPatient) current.push('Selecionar paciente')
    if (!selectedItem) current.push('Selecionar item da prescrição')
    if (!quantity || requestedQty <= 0) current.push('Informar quantidade maior que zero')
    if (selectedItem && requestedQty > prescribedQty) current.push('Quantidade acima do prescrito')
    if (selectedItem && !loadingLots && requestedQty > 0 && availableQty < requestedQty) {
      current.push('Estoque FEFO insuficiente')
    }
    if (selectedControlled && !notes.trim()) current.push('Registrar observação Portaria 344')
    return current
  }, [
    availableQty,
    loadingLots,
    notes,
    prescribedQty,
    quantity,
    requestedQty,
    selectedControlled,
    selectedItem,
    selectedPatient,
  ])

  const ready = blockers.length === 0

  // Single dispense submission with identical params — reused on retry after a
  // dose-safety override. Throws ApiError on non-ok so the dose-safety block
  // (HTTP 409 + code:'dose_safety_block') can be detected by the caller.
  const submitDispense = useCallback(async () => {
    if (!selectedItem) return
    const token = getAccessToken()
    if (!token) {
      setError('Sessão expirada')
      return
    }

    setSaving(true)
    setError('')
    try {
      const response = await fetch('/api/v1/pharmacy/dispense/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          prescription_item_id: selectedItem.id,
          quantity: requestedQty,
          notes,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new ApiError(response.status, data)
      }
      setDoseBlock(null)
      setResult(data)
      if (selectedPatient) await loadPrescriptions(selectedPatient.id)
      await loadLots(selectedItem.drug)
    } catch (err) {
      const block = isDoseSafetyBlock(err)
      if (block) {
        // Dose-safety interception: open the modal instead of the generic error.
        setDoseBlock(block)
        return
      }
      setError(err instanceof ApiError ? extractError(err.body) : 'Erro ao dispensar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }, [loadLots, loadPrescriptions, notes, requestedQty, selectedItem, selectedPatient])

  const handleDispense = async (event: FormEvent) => {
    event.preventDefault()
    if (!selectedItem) return
    if (blockers.length > 0) {
      setError(`Pendências antes de dispensar: ${blockers.join(', ')}.`)
      return
    }
    await submitDispense()
  }

  return (
    <PageShell variant="workbench">
        {doseBlock && selectedPatient && (
          <DoseSafetyModal
            block={doseBlock}
            patientId={selectedPatient.id}
            onResolved={() => {
              setDoseBlock(null)
              void submitDispense()
            }}
            onClose={() => setDoseBlock(null)}
          />
        )}
        <header className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold text-[#24292F]">Bancada de Dispensação</h1>
            <p className="text-sm text-[#8C959F]">
              Paciente, prescrição, FEFO, controle especial e fechamento permanecem visíveis.
            </p>
          </div>
          <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${
            ready
              ? 'border-green-200 bg-green-50 text-green-700'
              : 'border-yellow-200 bg-yellow-50 text-yellow-800'
          }`}>
            {ready ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {ready ? 'Pronta para dispensar' : `${blockers.length} pendência(s)`}
          </span>
        </header>

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <Search size={14} />
              Paciente
            </div>
            <p className="mt-2 truncate text-sm font-semibold text-[#24292F]">
              {loadingPrefill ? 'Carregando paciente...' : selectedPatient?.full_name ?? 'Nenhum selecionado'}
            </p>
            <p className="mt-1 truncate font-mono text-xs text-[#8C959F]">{patientMrn(selectedPatient, selectedRx)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <ClipboardList size={14} />
              Prescrições
            </div>
            <p className="mt-2 text-sm font-semibold text-[#24292F]">{prescriptions.length} receita(s)</p>
            <p className="mt-1 text-xs text-[#8C959F]">{totalItems} item(ns) liberado(s)</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <PackageSearch size={14} />
              FEFO
            </div>
            <p className="mt-2 text-sm font-semibold text-[#24292F]">{loadingLots ? 'Verificando...' : `${formatQty(availableQty)} disponível`}</p>
            <p className="mt-1 text-xs text-[#8C959F]">{lots.length} lote(s) elegível(is)</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-[#F4F7FA] p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <ShieldAlert size={14} />
              Portaria
            </div>
            <p className="mt-2 text-sm font-semibold text-[#24292F]">{controlledItems} item(ns) controlado(s)</p>
            <p className="mt-1 text-xs text-[#8C959F]">{selectedControlled ? 'Observação obrigatória' : 'Sem bloqueio no item'}</p>
          </div>
        </section>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {result && selectedItem && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
            <p className="font-semibold">Dispensação registrada</p>
            <p className="mt-1">
              {formatQty(result.total_quantity)} {selectedItem.unit_of_measure || 'un'} de {selectedItem.drug_name} em {result.lots.length} lote(s).
            </p>
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
          <div className="space-y-4">
            <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
              <div className="border-b border-slate-100 px-4 py-3">
                <h3 className="text-base font-semibold text-[#24292F]">Busca e contexto do paciente</h3>
                <p className="text-xs text-[#8C959F]">A fila de receitas aparece abaixo sem retornar para outra tela.</p>
              </div>
              <div className="space-y-3 p-4">
                <label htmlFor="patient-search" className="block text-xs font-medium text-[#57606A]">
                  Buscar paciente
                </label>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-2.5 text-slate-400" size={16} />
                  <input
                    id="patient-search"
                    type="text"
                    placeholder="Nome, CPF ou prontuário"
                    value={patientQuery}
                    onChange={(event) => {
                      setPatientQuery(event.target.value)
                      searchPatients(event.target.value)
                    }}
                    className="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                {loadingPatients && <p className="text-sm text-slate-400">Buscando pacientes...</p>}
                {patients.length > 0 && (
                  <div className="overflow-hidden rounded-lg border border-slate-200">
                    {patients.map((patient) => (
                      <button
                        type="button"
                        key={patient.id}
                        onClick={() => selectPatient(patient)}
                        className="flex w-full items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5 text-left last:border-b-0 hover:bg-[#F4F7FA]"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-[#24292F]">{patient.full_name}</span>
                          <span className="block truncate font-mono text-xs text-[#8C959F]">
                            {patient.medical_record_number ?? 'MRN pendente'}
                          </span>
                        </span>
                        <span className="text-xs text-slate-400">{formatDate(patient.birth_date)}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
              <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-[#24292F]">Itens para dispensar</h3>
                  <p className="text-xs text-[#8C959F]">Status, prescrição, posologia, controle especial e ação ficam na mesma grade.</p>
                </div>
                {selectedPatient && (
                  <button
                    type="button"
                    onClick={() => loadPrescriptions(selectedPatient.id)}
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-[#57606A] hover:bg-[#F4F7FA] focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <RotateCcw size={14} />
                    Atualizar
                  </button>
                )}
              </div>

              <div className="hidden grid-cols-[96px_minmax(0,1fr)_120px_130px] gap-3 border-b border-slate-100 px-4 py-2 text-xs font-semibold uppercase text-slate-400 lg:grid">
                <span>Status</span>
                <span>Medicamento / posologia</span>
                <span>Prescrito</span>
                <span>Ação</span>
              </div>

              <div className="divide-y divide-slate-100">
                {!selectedPatient && !loadingPrefill && (
                  <div className="px-4 py-10 text-center">
                    <p className="text-sm font-semibold text-[#57606A]">Selecione um paciente para abrir a fila.</p>
                    <p className="mt-1 text-xs text-[#8C959F]">O cockpit pode abrir esta bancada já com paciente preenchido.</p>
                  </div>
                )}
                {selectedPatient && loadingRx && (
                  <div className="px-4 py-10 text-center text-sm text-slate-400">Carregando prescrições assinadas...</div>
                )}
                {selectedPatient && !loadingRx && prescriptions.length === 0 && (
                  <div className="px-4 py-10 text-center">
                    <p className="text-sm font-semibold text-[#57606A]">Nenhuma prescrição assinada para dispensar.</p>
                    <p className="mt-1 text-xs text-[#8C959F]">Rascunhos e receitas canceladas não entram na fila da farmácia.</p>
                  </div>
                )}
                {prescriptions.map((rx) => (
                  <div key={rx.id} className="divide-y divide-slate-100">
                    <div className="bg-[#F4F7FA] px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge
                          meta={resolveBadgeMeta(
                            PRESCRIPTION_STATUS_META,
                            rx.status,
                            rx.status_display,
                          )}
                        />
                        <span className="text-xs text-[#8C959F]">{formatDate(rx.created_at)}</span>
                        <span className="text-xs text-[#8C959F]">{rx.prescriber_name || 'Prescritor não informado'}</span>
                      </div>
                    </div>
                    {rx.items.map((item) => (
                      <div
                        key={item.id}
                        className={`grid gap-3 px-4 py-3 lg:grid-cols-[96px_minmax(0,1fr)_120px_130px] lg:items-center ${
                          selectedItem?.id === item.id ? 'bg-blue-50/40' : ''
                        }`}
                      >
                        <div>
                          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${
                            selectedItem?.id === item.id
                              ? 'border-blue-200 bg-blue-50 text-blue-700'
                              : item.drug_is_controlled
                              ? 'border-orange-200 bg-orange-50 text-orange-700'
                              : 'border-green-200 bg-green-50 text-green-700'
                          }`}>
                            {itemStatus(item, selectedItem)}
                          </span>
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Pill size={15} className="shrink-0 text-slate-400" />
                            <p className="truncate text-sm font-semibold text-[#24292F]">{item.drug_name}</p>
                          </div>
                          {item.drug_generic_name && (
                            <p className="mt-1 truncate text-xs text-[#8C959F]">{item.drug_generic_name}</p>
                          )}
                          {item.dosage_instructions && (
                            <p className="mt-1 line-clamp-2 text-xs text-[#8C959F]">{item.dosage_instructions}</p>
                          )}
                        </div>
                        <div>
                          <span className="block text-xs font-medium text-[#8C959F] lg:hidden">Prescrito</span>
                          <p className="font-mono text-sm font-semibold text-[#24292F]">
                            {formatQty(item.quantity)} {item.unit_of_measure || 'un'}
                          </p>
                        </div>
                        <div>
                          <button
                            type="button"
                            onClick={() => selectItem(rx, item)}
                            className="w-full rounded-lg bg-gradient-to-b from-[#0066A1] to-[#005282] border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] px-3 py-2 text-sm font-semibold text-white hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] focus:outline-none focus:ring-2 focus:ring-blue-500"
                          >
                            Fechar item
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </section>
          </div>

          <aside>
            <form onSubmit={handleDispense} noValidate className="sticky top-4 rounded-lg border border-slate-200 bg-[#F4F7FA]">
              <div className="border-b border-slate-100 px-4 py-3">
                <h3 className="text-base font-semibold text-[#24292F]">Fechamento</h3>
                <p className="text-xs text-[#8C959F]">Quantidade, lotes FEFO e registro auditável.</p>
              </div>
              <div className="space-y-4 p-4">
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between gap-3">
                    <span className="text-[#8C959F]">Paciente</span>
                    <span className="max-w-[210px] truncate text-right font-medium text-[#24292F]">
                      {selectedPatient?.full_name ?? 'Pendente'}
                    </span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-[#8C959F]">Medicamento</span>
                    <span className="max-w-[210px] truncate text-right font-medium text-[#24292F]">
                      {selectedItem?.drug_name ?? 'Pendente'}
                    </span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-[#8C959F]">Prescrito</span>
                    <span className="font-mono font-medium text-[#24292F]">
                      {selectedItem ? `${formatQty(selectedItem.quantity)} ${selectedItem.unit_of_measure || 'un'}` : '-'}
                    </span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-[#8C959F]">FEFO disponível</span>
                    <span className="font-mono font-medium text-[#24292F]">{formatQty(availableQty)}</span>
                  </div>
                </div>

                <div>
                  <label htmlFor="dispense-quantity" className="mb-1 block text-xs font-medium text-[#57606A]">
                    Quantidade a dispensar
                  </label>
                  <input
                    id="dispense-quantity"
                    type="number"
                    step="0.001"
                    min="0.001"
                    value={quantity}
                    onChange={(event) => setQuantity(event.target.value)}
                    placeholder={selectedItem ? selectedItem.quantity : '0'}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div className="rounded-lg border border-slate-200 p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[#24292F]">
                    <PackageSearch size={15} />
                    Lotes FEFO
                  </div>
                  {loadingLots && <p className="text-sm text-slate-400">Verificando estoque...</p>}
                  {!loadingLots && !selectedItem && (
                    <p className="text-sm text-[#8C959F]">Selecione um item para ver os lotes elegíveis.</p>
                  )}
                  {!loadingLots && selectedItem && lots.length === 0 && (
                    <p className="text-sm font-medium text-red-700">Nenhum lote disponível para este medicamento.</p>
                  )}
                  {!loadingLots && lots.length > 0 && (
                    <div className="space-y-2">
                      {lots.slice(0, 5).map((lot) => (
                        <div key={lot.id} className="rounded-lg bg-[#F4F7FA] px-3 py-2 text-xs">
                          <div className="flex items-center justify-between gap-3">
                            <span className="truncate font-mono font-semibold text-slate-800">Lote {lot.lot_number || '-'}</span>
                            <span className="font-mono text-[#57606A]">{formatQty(lot.quantity)}</span>
                          </div>
                          <p className="mt-1 text-[#8C959F]">
                            Validade {formatDate(lot.expiry_date)}{lot.location ? ` - ${lot.location}` : ''}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <label htmlFor="dispense-notes" className="mb-1 block text-xs font-medium text-[#57606A]">
                    Observações de dispensação
                    {selectedControlled && <span className="text-red-600"> *</span>}
                  </label>
                  <textarea
                    id="dispense-notes"
                    rows={4}
                    value={notes}
                    onChange={(event) => setNotes(event.target.value)}
                    placeholder={
                      selectedControlled
                        ? 'Registro obrigatório para medicamento controlado.'
                        : 'Orientações ao paciente, intercorrências ou referência interna.'
                    }
                    className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <ReadinessPanel
                  blockers={blockers}
                  readyText="Sem bloqueios. A dispensação pode ser registrada."
                />

                <button
                  type="submit"
                  disabled={saving}
                  className="w-full rounded-lg bg-gradient-to-b from-[#0066A1] to-[#005282] border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] py-2.5 text-sm font-semibold text-white hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {saving ? 'Dispensando...' : 'Confirmar dispensação'}
                </button>
                <button
                  type="button"
                  onClick={reset}
                  className="w-full rounded-lg py-2 text-sm font-medium text-[#57606A] hover:bg-[#F4F7FA] focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  Nova dispensação
                </button>
              </div>
            </form>
          </aside>
        </div>
    </PageShell>
  )
}
