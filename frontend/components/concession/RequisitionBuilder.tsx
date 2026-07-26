'use client'

import { useState } from 'react'
import { X, Plus, Trash2 } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import {
  LOGISTICS_ENDPOINTS,
  type FacilityOption,
  type MaterialOption,
  type SupplyRequisition,
} from './logisticsMeta'

interface LineItem {
  material: string
  quantity: string
}

interface RequisitionBuilderProps {
  open: boolean
  facilities: FacilityOption[]
  materials: MaterialOption[]
  onClose: () => void
  onCreated: (requisition: SupplyRequisition) => void
}

const INPUT_CLASS =
  'w-full rounded-lg border border-slate-200 bg-neu-panel px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500'

function emptyLine(): LineItem {
  return { material: '', quantity: '1' }
}

export default function RequisitionBuilder({
  open,
  facilities,
  materials,
  onClose,
  onCreated,
}: RequisitionBuilderProps) {
  const [facility, setFacility] = useState('')
  const [notes, setNotes] = useState('')
  const [items, setItems] = useState<LineItem[]>([emptyLine()])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  const validLines = items.filter((l) => l.material && Number(l.quantity) > 0)
  const ready = Boolean(facility) && validLines.length > 0

  function updateLine(idx: number, key: keyof LineItem, value: string) {
    setItems((current) => current.map((l, i) => (i === idx ? { ...l, [key]: value } : l)))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!ready) {
      setError('Selecione a unidade e ao menos um material com quantidade.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const created = await apiFetch<SupplyRequisition>(LOGISTICS_ENDPOINTS.requisitions, {
        method: 'POST',
        body: JSON.stringify({
          requesting_facility: facility,
          notes,
          items: validLines.map((l) => ({ material: l.material, quantity: l.quantity })),
        }),
      })
      onCreated(created)
      setFacility('')
      setNotes('')
      setItems([emptyLine()])
    } catch {
      setError('Erro ao criar requisição.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">Nova requisição de suprimentos</h2>
          <button type="button" onClick={onClose} aria-label="Fechar" className="text-slate-400 hover:text-slate-600">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="space-y-4 px-5 py-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <div>
            <label htmlFor="req-facility" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Unidade solicitante *
            </label>
            <select
              id="req-facility"
              value={facility}
              onChange={(e) => setFacility(e.target.value)}
              required
              className={INPUT_CLASS}
            >
              <option value="">Selecionar unidade</option>
              {facilities.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-neu-inkSoft">Itens *</span>
              <button
                type="button"
                onClick={() => setItems((i) => [...i, emptyLine()])}
                className="inline-flex items-center gap-1 text-xs font-medium text-neu-brand hover:underline"
              >
                <Plus size={14} /> Adicionar item
              </button>
            </div>
            <div className="space-y-2">
              {items.map((line, idx) => (
                <div key={idx} className="flex gap-2">
                  <label htmlFor={`req-item-material-${idx}`} className="sr-only">
                    Material do item {idx + 1}
                  </label>
                  <select
                    id={`req-item-material-${idx}`}
                    value={line.material}
                    onChange={(e) => updateLine(idx, 'material', e.target.value)}
                    className={`${INPUT_CLASS} flex-1`}
                  >
                    <option value="">Selecionar material</option>
                    {materials.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                  <label htmlFor={`req-item-qty-${idx}`} className="sr-only">
                    Quantidade do item {idx + 1}
                  </label>
                  <input
                    id={`req-item-qty-${idx}`}
                    type="number"
                    min="0"
                    step="0.001"
                    value={line.quantity}
                    onChange={(e) => updateLine(idx, 'quantity', e.target.value)}
                    className={`${INPUT_CLASS} w-24`}
                  />
                  {items.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setItems((i) => i.filter((_, ii) => ii !== idx))}
                      aria-label={`Remover item ${idx + 1}`}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-red-500 hover:bg-red-50"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="req-notes" className="mb-1 block text-xs font-medium text-neu-inkSoft">
              Observações
            </label>
            <textarea
              id="req-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className={INPUT_CLASS}
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="rounded-lg px-4 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-app">
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {saving ? 'Criando...' : 'Criar requisição'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
