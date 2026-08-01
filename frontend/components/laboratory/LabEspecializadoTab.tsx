'use client'

import { useCallback, useEffect, useState } from 'react'
import { FilePlus2 } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { normalizeList, type ListResponse } from './especializado-types'
import MicrobiologyPanel from './MicrobiologyPanel'
import PathologyPanel from './PathologyPanel'
import MicrobiologyResultForm from './MicrobiologyResultForm'
import PathologyReportForm from './PathologyReportForm'

interface Props {
  patientId: string
  /** `emr.read` — gates the read panels. */
  canRead: boolean
  /** `emr.write` — gates launching new structured results. */
  canWrite: boolean
}

interface LabItemLite {
  id: string
  test_name: string
  category?: string
}
interface LabOrderLite {
  id: string
  items: LabItemLite[]
}

/**
 * Aba "Lab especializado" do prontuário: microbiologia (culturas + antibiograma
 * S/I/R) e anatomia patológica (laudos + espécimes), com lançamento estruturado
 * (emr.write) dos pedidos de lab do paciente. Read-only para quem só tem emr.read.
 */
export default function LabEspecializadoTab({ patientId, canRead, canWrite }: Props) {
  const [orders, setOrders] = useState<LabOrderLite[]>([])
  const [reloadToken, setReloadToken] = useState(0)
  const [microItem, setMicroItem] = useState('')
  const [apItem, setApItem] = useState('')
  const [microFormFor, setMicroFormFor] = useState<string | null>(null)
  const [apFormFor, setApFormFor] = useState<string | null>(null)

  const loadOrders = useCallback(async () => {
    if (!patientId || !canWrite) return
    try {
      const data = await apiFetch<ListResponse<LabOrderLite> | LabOrderLite[]>(
        `/api/v1/lab-orders/?patient=${patientId}`,
      )
      setOrders(normalizeList(data))
    } catch {
      setOrders([])
    }
  }, [patientId, canWrite])

  useEffect(() => {
    loadOrders()
  }, [loadOrders])

  const allItems = orders.flatMap((o) => o.items ?? [])
  const microItems = allItems.filter((i) => i.category === 'microbiology')
  const apItems = allItems.filter((i) => i.category === 'pathology')

  const afterCreate = useCallback(() => {
    setMicroFormFor(null)
    setApFormFor(null)
    setReloadToken((n) => n + 1)
    loadOrders()
  }, [loadOrders])

  function ItemPicker({
    items,
    value,
    onChange,
    onLaunch,
    label,
  }: {
    items: LabItemLite[]
    value: string
    onChange: (v: string) => void
    onLaunch: () => void
    label: string
  }) {
    if (items.length === 0) return null
    return (
      <div className="flex flex-wrap items-end gap-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">{label}</span>
          <select
            aria-label={label}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm text-neu-ink"
          >
            <option value="">Selecione o pedido...</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.test_name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!value}
          onClick={onLaunch}
          className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50"
        >
          <FilePlus2 size={15} /> Lançar
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <section aria-label="Microbiologia">
        <h3 className="mb-3 text-base font-semibold text-neu-ink">Microbiologia</h3>
        {canWrite && !microFormFor && (
          <div className="mb-3">
            <ItemPicker
              items={microItems}
              value={microItem}
              onChange={setMicroItem}
              onLaunch={() => setMicroFormFor(microItem)}
              label="Novo resultado de microbiologia"
            />
          </div>
        )}
        {microFormFor && (
          <div className="mb-3">
            <MicrobiologyResultForm
              orderItemId={microFormFor}
              onCreated={afterCreate}
              onCancel={() => setMicroFormFor(null)}
            />
          </div>
        )}
        <MicrobiologyPanel key={`micro-${reloadToken}`} patientId={patientId} canRead={canRead} />
      </section>

      <section aria-label="Anatomia patológica">
        <h3 className="mb-3 text-base font-semibold text-neu-ink">Anatomia patológica</h3>
        {canWrite && !apFormFor && (
          <div className="mb-3">
            <ItemPicker
              items={apItems}
              value={apItem}
              onChange={setApItem}
              onLaunch={() => setApFormFor(apItem)}
              label="Novo laudo anatomopatológico"
            />
          </div>
        )}
        {apFormFor && (
          <div className="mb-3">
            <PathologyReportForm
              orderItemId={apFormFor}
              onCreated={afterCreate}
              onCancel={() => setApFormFor(null)}
            />
          </div>
        )}
        <PathologyPanel key={`ap-${reloadToken}`} patientId={patientId} canRead={canRead} />
      </section>
    </div>
  )
}
