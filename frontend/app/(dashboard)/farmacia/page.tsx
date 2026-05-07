'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  PackageCheck,
  Pill,
  ShieldAlert,
  Truck,
} from 'lucide-react'
import { getAccessToken } from '@/lib/auth'

type ApiList<T> = T[] | { results?: T[]; count?: number }

type RxItem = {
  id: string
  drug: string
  drug_name: string
  drug_generic_name?: string
  drug_is_controlled: boolean
  quantity: string
  unit_of_measure: string
  dosage_instructions?: string
}

type Prescription = {
  id: string
  patient: string
  patient_name?: string
  patient_mrn?: string
  prescriber_name?: string
  status: string
  status_display?: string
  created_at?: string
  items: RxItem[]
}

type StockItem = {
  id: string
  drug_name: string | null
  material_name: string | null
  lot_number: string
  expiry_date: string | null
  quantity: string
  min_stock: string
  location: string
  is_expired: boolean
  is_low_stock: boolean
}

type Dispensation = {
  id: string
  drug_name?: string | null
  total_quantity: string
  dispensed_by_name?: string | null
  dispensed_at?: string
  lots: { stock_item: string; quantity: string }[]
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

function itemName(item: StockItem) {
  return item.drug_name ?? item.material_name ?? 'Item sem nome'
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  return value.slice(0, 10)
}

function daysUntil(date?: string | null) {
  if (!date) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(`${date}T00:00:00`)
  return Math.ceil((target.getTime() - today.getTime()) / 86400000)
}

function patientLabel(rx: Prescription) {
  return rx.patient_name ?? 'Paciente sem nome no retorno'
}

export default function FarmaciaPage() {
  const [signedRx, setSignedRx] = useState<Prescription[]>([])
  const [partialRx, setPartialRx] = useState<Prescription[]>([])
  const [stock, setStock] = useState<StockItem[]>([])
  const [dispensations, setDispensations] = useState<Dispensation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    Promise.all([
      apiGet<ApiList<Prescription>>('/prescriptions/?status=signed'),
      apiGet<ApiList<Prescription>>('/prescriptions/?status=partially_dispensed'),
      apiGet<ApiList<StockItem>>('/pharmacy/stock/items/'),
      apiGet<ApiList<Dispensation>>('/pharmacy/dispensations/'),
    ])
      .then(([signedData, partialData, stockData, dispData]) => {
        if (!active) return
        setSignedRx(listFromResponse(signedData))
        setPartialRx(listFromResponse(partialData))
        setStock(listFromResponse(stockData))
        setDispensations(listFromResponse(dispData))
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : 'Não foi possível carregar farmácia.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  const queue = useMemo(() => [...signedRx, ...partialRx], [signedRx, partialRx])
  const controlledQueue = queue.reduce(
    (sum, rx) => sum + rx.items.filter((item) => item.drug_is_controlled).length,
    0,
  )
  const lowStock = stock.filter((item) => item.is_low_stock && !item.is_expired)
  const expiringStock = stock.filter((item) => {
    const days = daysUntil(item.expiry_date)
    return days !== null && days >= 0 && days <= 30
  })
  const expiredStock = stock.filter((item) => item.is_expired)
  const totalUnits = stock.reduce((sum, item) => sum + parseQty(item.quantity), 0)
  const alertItems = [...expiredStock, ...expiringStock, ...lowStock]
    .filter((item, index, items) => items.findIndex((candidate) => candidate.id === item.id) === index)
    .slice(0, 8)
  const recentDispensations = dispensations.slice(0, 6)

  return (
    <div className="min-h-full bg-slate-50">
      <div className="mx-auto max-w-[1500px] space-y-4">
        <header className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-2xl font-semibold text-slate-900">Cockpit de Farmácia</h2>
            <p className="text-sm text-slate-500">
              Fila de prescrições, estoque crítico, validade e dispensações recentes em uma superfície.
            </p>
          </div>
          <Link
            href="/farmacia/dispense"
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Abrir dispensação
            <ArrowRight size={16} />
          </Link>
        </header>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <ClipboardList size={14} />
              Fila assinada
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{loading ? '-' : queue.length}</p>
            <p className="text-xs text-slate-500">Receitas liberadas para dispensar</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <ShieldAlert size={14} />
              Controlados
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{loading ? '-' : controlledQueue}</p>
            <p className="text-xs text-slate-500">Itens exigindo registro Portaria 344</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <PackageCheck size={14} />
              Estoque crítico
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{loading ? '-' : lowStock.length}</p>
            <p className="text-xs text-slate-500">{formatQty(totalUnits)} unidade(s) rastreadas</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-400">
              <Truck size={14} />
              Validade
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{loading ? '-' : expiringStock.length}</p>
            <p className="text-xs text-slate-500">{expiredStock.length} lote(s) vencido(s)</p>
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
          <section className="rounded-lg border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
              <div className="min-w-0 flex-1">
                <h3 className="text-base font-semibold text-slate-900">Fila de dispensação</h3>
                <p className="text-xs text-slate-500">Receitas assinadas e parcialmente dispensadas aparecem sem troca de tela.</p>
              </div>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
                {queue.length} receita(s)
              </span>
            </div>

            <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_120px_120px] gap-3 border-b border-slate-100 px-4 py-2 text-xs font-semibold uppercase text-slate-400 lg:grid">
              <span>Paciente</span>
              <span>Prescrição</span>
              <span>Risco</span>
              <span>Ação</span>
            </div>

            <div className="divide-y divide-slate-100">
              {loading && (
                <div className="px-4 py-10 text-center text-sm text-slate-400">Carregando fila de farmácia...</div>
              )}
              {!loading && queue.length === 0 && (
                <div className="px-4 py-10 text-center">
                  <p className="text-sm font-semibold text-slate-700">Nenhuma prescrição liberada para dispensação.</p>
                  <p className="mt-1 text-xs text-slate-500">Quando o CPOE assinar uma receita, ela aparece aqui.</p>
                </div>
              )}
              {queue.map((rx) => {
                const itemCount = rx.items.length
                const controlledCount = rx.items.filter((item) => item.drug_is_controlled).length
                return (
                  <div
                    key={rx.id}
                    className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_120px_120px] lg:items-center"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">{patientLabel(rx)}</p>
                      <p className="mt-1 truncate font-mono text-xs text-slate-500">{rx.patient_mrn ?? 'MRN pendente'}</p>
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                          rx.status === 'partially_dispensed'
                            ? 'border-blue-200 bg-blue-50 text-blue-700'
                            : 'border-green-200 bg-green-50 text-green-700'
                        }`}>
                          {rx.status_display ?? rx.status}
                        </span>
                        <span className="text-xs text-slate-500">{formatDate(rx.created_at)}</span>
                      </div>
                      <p className="mt-1 truncate text-xs text-slate-500">
                        {itemCount} item(ns) - {rx.prescriber_name || 'Prescritor não informado'}
                      </p>
                    </div>
                    <div>
                      {controlledCount > 0 ? (
                        <span className="inline-flex rounded-full border border-orange-200 bg-orange-50 px-2 py-0.5 text-xs font-semibold text-orange-700">
                          {controlledCount} controlado(s)
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700">
                          <CheckCircle2 size={12} />
                          Sem Portaria
                        </span>
                      )}
                    </div>
                    <div>
                      <Link
                        href={`/farmacia/dispense?patient=${rx.patient}`}
                        className="inline-flex items-center gap-2 rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        Dispensar
                        <ArrowRight size={14} />
                      </Link>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>

          <aside className="space-y-4">
            <section className="rounded-lg border border-slate-200 bg-white">
              <div className="border-b border-slate-100 px-4 py-3">
                <h3 className="text-base font-semibold text-slate-900">Alertas de estoque</h3>
                <p className="text-xs text-slate-500">Baixo, vencido ou vencendo em 30 dias.</p>
              </div>
              <div className="divide-y divide-slate-100">
                {loading && <p className="px-4 py-6 text-sm text-slate-400">Carregando estoque...</p>}
                {!loading && alertItems.length === 0 && (
                  <p className="px-4 py-6 text-sm text-green-700">Sem alertas críticos no estoque.</p>
                )}
                {alertItems.map((item) => {
                  const days = daysUntil(item.expiry_date)
                  const status = item.is_expired
                    ? 'Vencido'
                    : days !== null && days <= 30
                    ? `Vence em ${days}d`
                    : 'Estoque baixo'
                  return (
                    <Link
                      key={item.id}
                      href={`/farmacia/stock/${item.id}`}
                      className="block px-4 py-3 hover:bg-slate-50"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-slate-900">{itemName(item)}</p>
                          <p className="mt-1 truncate font-mono text-xs text-slate-500">
                            Lote {item.lot_number || '-'} - {item.location || 'sem local'}
                          </p>
                        </div>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-semibold ${
                          item.is_expired
                            ? 'border-red-200 bg-red-50 text-red-700'
                            : days !== null && days <= 30
                            ? 'border-yellow-200 bg-yellow-50 text-yellow-800'
                            : 'border-orange-200 bg-orange-50 text-orange-700'
                        }`}>
                          {status}
                        </span>
                      </div>
                      <p className="mt-2 text-xs text-slate-500">
                        {formatQty(item.quantity)} disponível - mínimo {formatQty(item.min_stock)}
                      </p>
                    </Link>
                  )
                })}
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white">
              <div className="border-b border-slate-100 px-4 py-3">
                <h3 className="text-base font-semibold text-slate-900">Dispensações recentes</h3>
                <p className="text-xs text-slate-500">Últimos registros auditáveis.</p>
              </div>
              <div className="divide-y divide-slate-100">
                {loading && <p className="px-4 py-6 text-sm text-slate-400">Carregando dispensações...</p>}
                {!loading && recentDispensations.length === 0 && (
                  <p className="px-4 py-6 text-sm text-slate-500">Nenhuma dispensação registrada ainda.</p>
                )}
                {recentDispensations.map((disp) => (
                  <div key={disp.id} className="px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <Pill size={14} />
                      <span className="truncate">{disp.drug_name ?? 'Medicamento'}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatQty(disp.total_quantity)} dispensado(s) em {disp.lots.length} lote(s)
                    </p>
                    <p className="mt-1 truncate text-xs text-slate-400">
                      {formatDate(disp.dispensed_at)} - {disp.dispensed_by_name ?? 'Farmácia'}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  )
}
