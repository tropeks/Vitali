'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { getAccessToken } from '@/lib/auth'

function extractError(err: any): string {
  if (typeof err === 'string') return err
  if (err?.detail) return String(err.detail)
  const firstVal = Object.values(err ?? {})[0]
  if (Array.isArray(firstVal)) return String(firstVal[0])
  if (typeof firstVal === 'string') return firstVal
  return 'Erro ao dispensar. Tente novamente.'
}

type Patient = { id: string; full_name: string; birth_date: string }
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
  prescriber_name: string
  status: string
  is_signed: boolean
  created_at: string
  items: RxItem[]
}
type Lot = { id: string; lot_number: string; expiry_date: string | null; quantity: string }
type DispenseResult = {
  id: string
  total_quantity: string
  lots: { stock_item: string; quantity: string }[]
}

type Step = 'search' | 'items' | 'confirm' | 'success'

const STEP_LABELS: Record<string, string> = {
  search: 'Buscar paciente',
  items: 'Itens da receita',
  confirm: 'Confirmar',
}

export default function DispensePage() {
  const [step, setStep] = useState<Step>('search')
  const [patientQuery, setPatientQuery] = useState('')
  const [patients, setPatients] = useState<Patient[]>([])
  const [loadingPatients, setLoadingPatients] = useState(false)
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

  const searchPatientsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const searchPatientsNow = useCallback(async (q: string) => {
    if (!q.trim()) { setPatients([]); return }
    setLoadingPatients(true)
    try {
      const token = getAccessToken()
      const res = await fetch(`/api/v1/emr/patients/?search=${encodeURIComponent(q)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setPatients(data.results ?? data ?? [])
    } finally { setLoadingPatients(false) }
  }, [])

  const searchPatients = useCallback((q: string) => {
    if (searchPatientsTimerRef.current) clearTimeout(searchPatientsTimerRef.current)
    searchPatientsTimerRef.current = setTimeout(() => searchPatientsNow(q), 300)
  }, [searchPatientsNow])

  const selectPatient = async (patient: Patient) => {
    setSelectedPatient(patient)
    setPatients([])
    setPatientQuery(patient.full_name)
    setLoadingRx(true)
    try {
      const token = getAccessToken()
      const res = await fetch(`/api/v1/emr/prescriptions/?patient=${patient.id}&status=signed`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setPrescriptions(data.results ?? data ?? [])
      setStep('items')
    } finally { setLoadingRx(false) }
  }

  const selectItem = (rx: Prescription, item: RxItem) => {
    setSelectedRx(rx)
    setSelectedItem(item)
    setQuantity('')
    setNotes('')
    setLots([])
    setError('')
    setStep('confirm')
  }

  const fetchLotsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchLotsNow = useCallback(async (drugId: string, qty: string) => {
    if (!drugId || !qty || parseFloat(qty) <= 0) { setLots([]); return }
    setLoadingLots(true)
    try {
      const token = getAccessToken()
      const res = await fetch(`/api/v1/pharmacy/stock/availability/?drug=${drugId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      setLots(data.available_lots ?? [])
    } finally { setLoadingLots(false) }
  }, [])

  const fetchLots = useCallback((drugId: string, qty: string) => {
    if (fetchLotsTimerRef.current) clearTimeout(fetchLotsTimerRef.current)
    fetchLotsTimerRef.current = setTimeout(() => fetchLotsNow(drugId, qty), 400)
  }, [fetchLotsNow])

  useEffect(() => {
    if (selectedItem && quantity) fetchLots(selectedItem.drug, quantity)
  }, [quantity, selectedItem, fetchLots])

  const handleDispense = async () => {
    if (!selectedItem) return
    setSaving(true)
    setError('')
    try {
      const token = getAccessToken()
      if (!token) { setError('Sessão expirada'); setSaving(false); return }
      const res = await fetch('/api/v1/pharmacy/dispense/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          prescription_item_id: selectedItem.id,
          quantity: parseFloat(quantity),
          notes,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(extractError(data))
        return
      }
      setResult(data)
      setStep('success')
    } finally { setSaving(false) }
  }

  const reset = () => {
    setStep('search')
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

  return (
    <div className="max-w-3xl space-y-5">
      {/* Step indicator */}
      <div className="flex items-center gap-2 text-xs text-slate-400">
        {(['search', 'items', 'confirm'] as const).map((s, i) => {
          const done =
            (s === 'search' && ['items', 'confirm', 'success'].includes(step)) ||
            (s === 'items' && ['confirm', 'success'].includes(step))
          const active = step === s || (step === 'success' && s === 'confirm')
          return (
            <span key={s} className="flex items-center gap-2">
              {i > 0 && <span className="text-slate-200">›</span>}
              <span className={
                done ? 'text-green-600 font-medium' :
                active ? 'text-blue-600 font-medium' :
                'text-slate-400'
              }>
                {i + 1}. {STEP_LABELS[s]}
              </span>
            </span>
          )
        })}
      </div>

      {/* Step 1: Search patient */}
      {(step === 'search' || step === 'items') && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
          <label className="block text-sm font-medium text-slate-700">Paciente</label>
          <input
            type="text"
            placeholder="Buscar por nome do paciente..."
            value={patientQuery}
            onChange={e => { setPatientQuery(e.target.value); searchPatients(e.target.value) }}
            className="w-full px-4 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {loadingPatients && <p className="text-sm text-slate-400">Buscando...</p>}
          {patients.length > 0 && (
            <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 overflow-hidden">
              {patients.map(p => (
                <button
                  key={p.id}
                  onClick={() => selectPatient(p)}
                  className="w-full text-left px-4 py-2.5 hover:bg-slate-50 transition-colors"
                >
                  <span className="text-sm font-medium text-slate-900">{p.full_name}</span>
                  <span className="text-xs text-slate-400 ml-2">{p.birth_date}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Step 2: Prescription items */}
      {step === 'items' && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {loadingRx && (
            <p className="px-6 py-4 text-sm text-slate-400">Carregando receitas...</p>
          )}
          {!loadingRx && prescriptions.length === 0 && (
            <div className="px-6 py-10 text-center space-y-1">
              <p className="text-sm font-medium text-slate-700">Nenhuma receita assinada</p>
              <p className="text-xs text-slate-400">
                Só receitas assinadas por um médico podem ser dispensadas.
              </p>
            </div>
          )}
          {prescriptions.map(rx => (
            <div key={rx.id} className="border-b border-slate-100 last:border-b-0">
              <div className="px-5 py-3 bg-slate-50 flex items-center justify-between">
                <div className="text-sm">
                  <span className="font-medium text-slate-900">Dr. {rx.prescriber_name}</span>
                  <span className="text-slate-400 ml-2 text-xs">{rx.created_at?.slice(0, 10)}</span>
                </div>
                <span className="px-2 py-0.5 text-xs bg-green-100 text-green-700 rounded font-medium">
                  Assinada ✓
                </span>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left px-5 py-2 text-xs font-medium text-slate-500">Medicamento</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-slate-500">Prescrito</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-slate-500">Tipo</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {rx.items.map(item => (
                    <tr key={item.id} className="border-b border-slate-50 hover:bg-slate-50">
                      <td className="px-5 py-3">
                        <p className="font-medium text-slate-900">{item.drug_name}</p>
                        {item.drug_generic_name && (
                          <p className="text-xs text-slate-400">{item.drug_generic_name}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-700 text-xs">
                        {item.quantity} {item.unit_of_measure || 'un'}
                      </td>
                      <td className="px-4 py-3">
                        {item.drug_is_controlled
                          ? <span className="px-2 py-0.5 text-xs bg-orange-100 text-orange-700 rounded font-medium">Controlado</span>
                          : <span className="text-slate-300 text-xs">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => selectItem(rx, item)}
                          className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700"
                        >
                          Dispensar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Step 3: Confirm */}
      {step === 'confirm' && selectedItem && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-5">
          <div>
            <button
              onClick={() => setStep('items')}
              className="text-xs text-blue-600 hover:underline mb-3 inline-block"
            >
              ← Voltar à receita
            </button>
            <h3 className="text-base font-semibold text-slate-900">{selectedItem.drug_name}</h3>
            <p className="text-sm text-slate-500">
              {selectedItem.drug_generic_name && `${selectedItem.drug_generic_name} • `}
              Prescrito: {selectedItem.quantity} {selectedItem.unit_of_measure || 'un'}
            </p>
            {selectedItem.drug_is_controlled && (
              <span className="inline-flex mt-2 px-2 py-0.5 text-xs bg-orange-100 text-orange-700 rounded font-medium">
                Medicamento controlado — observações obrigatórias
              </span>
            )}
          </div>

          {error && (
            <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Quantidade a dispensar *
            </label>
            <input
              type="number"
              step="0.001"
              min="0.001"
              max={selectedItem.quantity}
              placeholder={`Ex: ${selectedItem.quantity}`}
              className="w-48 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={quantity}
              onChange={e => setQuantity(e.target.value)}
            />
          </div>

          {/* FEFO lot preview */}
          {quantity && parseFloat(quantity) > 0 && (
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-2">
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                Lotes selecionados automaticamente (FEFO)
              </p>
              {loadingLots && <p className="text-xs text-slate-400">Verificando estoque...</p>}
              {!loadingLots && lots.length === 0 && (
                <p className="text-xs text-red-600 font-medium">
                  Estoque insuficiente ou nenhum lote disponível para esse medicamento.
                </p>
              )}
              {!loadingLots && lots.map(lot => (
                <div key={lot.id} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-slate-700 font-medium">Lote {lot.lot_number}</span>
                  {lot.expiry_date && (
                    <span className="text-slate-400">Val: {lot.expiry_date}</span>
                  )}
                  <span className="text-slate-600">{lot.quantity} un disponíveis</span>
                </div>
              ))}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Observações{' '}
              {selectedItem.drug_is_controlled
                ? <span className="text-red-600">* obrigatório (Portaria 344)</span>
                : <span className="text-slate-400">(opcional)</span>}
            </label>
            <textarea
              rows={3}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder={
                selectedItem.drug_is_controlled
                  ? 'Registro de dispensação controlada (Portaria 344)...'
                  : 'Posologia, orientações ao paciente...'
              }
              value={notes}
              onChange={e => setNotes(e.target.value)}
            />
          </div>

          <div className="flex gap-3 pt-1">
            <button
              onClick={handleDispense}
              disabled={
                saving ||
                !quantity ||
                parseFloat(quantity) <= 0 ||
                (selectedItem.drug_is_controlled && !notes.trim())
              }
              className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Dispensando...' : 'Confirmar Dispensação'}
            </button>
            <button
              onClick={() => setStep('items')}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-900"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Success */}
      {step === 'success' && result && selectedItem && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-4">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 bg-green-100 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
              <svg className="w-4 h-4 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <p className="text-base font-semibold text-slate-900">Dispensação registrada</p>
              <p className="text-sm text-slate-500 mt-0.5">
                {result.total_quantity} {selectedItem.unit_of_measure || 'un'} de{' '}
                <span className="font-medium text-slate-700">{selectedItem.drug_name}</span>{' '}
                dispensados em {result.lots.length} lote(s).
              </p>
            </div>
          </div>
          <div className="bg-slate-50 rounded-lg px-4 py-2">
            <p className="text-xs text-slate-400 font-mono">ID: {result.id}</p>
          </div>
          <div className="flex gap-3 pt-1">
            <button
              onClick={() => { setStep('items'); setError(''); setResult(null) }}
              className="px-4 py-2 text-sm font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50"
            >
              Dispensar outro item
            </button>
            <button
              onClick={reset}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-900"
            >
              Nova dispensação
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
