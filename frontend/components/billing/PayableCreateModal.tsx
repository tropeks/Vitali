import { useState } from 'react'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage } from '@/lib/admin'
import type { Payable } from './financeFormat'

interface PayableCreateModalProps {
  onClose: () => void
  onCreated: (payable: Payable) => void
}

/**
 * Create a Contas a pagar row. `status` is server-controlled (always born
 * 'planned' — maker-checker), so we only POST the mutable fields the serializer
 * accepts. `external_id` is the idempotency key required by the model.
 */
export default function PayableCreateModal({ onClose, onCreated }: PayableCreateModalProps) {
  const [description, setDescription] = useState('')
  const [externalId, setExternalId] = useState('')
  const [amount, setAmount] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [category, setCategory] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSave = description.trim() && externalId.trim() && amount.trim() && dueDate

  const submit = async () => {
    if (!canSave) return
    setSaving(true)
    setError(null)
    try {
      const created = await apiFetch<Payable>('/api/v1/billing/payables/', {
        method: 'POST',
        body: JSON.stringify({
          external_id: externalId.trim(),
          description: description.trim(),
          amount,
          due_date: dueDate,
          category: category.trim(),
          notes: notes.trim(),
        }),
      })
      onCreated(created)
    } catch (e) {
      setError(apiErrorMessage(e, 'Não foi possível criar a conta a pagar.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-label="Nova conta a pagar">
      <div className="w-full max-w-md space-y-4 rounded-xl bg-neu-panel p-4 shadow-neu-panel">
        <h2 className="text-lg font-semibold text-neu-ink">Nova conta a pagar</h2>
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}
        <label className="block text-sm text-neu-inkSoft">
          Descrição
          <input aria-label="Descrição" className="neu-input mt-1 block w-full" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="block text-sm text-neu-inkSoft">
          Identificador (external_id)
          <input aria-label="Identificador" className="neu-input mt-1 block w-full" value={externalId} onChange={(e) => setExternalId(e.target.value)} />
        </label>
        <div className="flex gap-3">
          <label className="block flex-1 text-sm text-neu-inkSoft">
            Valor
            <input aria-label="Valor" type="number" min="0" step="0.01" className="neu-input mt-1 block w-full" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="block flex-1 text-sm text-neu-inkSoft">
            Vencimento
            <input aria-label="Vencimento" type="date" className="neu-input mt-1 block w-full" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </label>
        </div>
        <label className="block text-sm text-neu-inkSoft">
          Categoria
          <input aria-label="Categoria" className="neu-input mt-1 block w-full" value={category} onChange={(e) => setCategory(e.target.value)} />
        </label>
        <label className="block text-sm text-neu-inkSoft">
          Observações
          <textarea aria-label="Observações" rows={2} className="neu-input mt-1 block w-full resize-none" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button className="neu-button-secondary" onClick={onClose} disabled={saving}>Cancelar</button>
          <button className="neu-button-primary" onClick={() => void submit()} disabled={!canSave || saving}>
            {saving ? 'Salvando…' : 'Criar'}
          </button>
        </div>
      </div>
    </div>
  )
}
