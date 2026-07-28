'use client'

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import type { CboOption, SigtapOption } from './sus-types'

interface Props {
  competenciaId: number
  /** Called after a BPA-C line is created. */
  onAdded: () => void
}

/**
 * Entrada manual de BPA-C (linha consolidada, sem paciente): procedimento SIGTAP
 * × CBO × idade (faixa) × quantidade. O `valor` é computado no backend. `sigtap`
 * é o pk INTEGER do catálogo (`/sigtap/?q=`); `cbo` é o pk do CBOCode — ver o
 * caveat em sus-types sobre o endpoint de CBO não expor o `id` hoje.
 */
export default function BpaConsolidadoForm({ competenciaId, onAdded }: Props) {
  const [sigtap, setSigtap] = useState<SigtapOption | null>(null)
  const [cbo, setCbo] = useState<CboOption | null>(null)
  const [idade, setIdade] = useState('')
  const [quantidade, setQuantidade] = useState('1')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const canSubmit =
    sigtap != null && cbo != null && idade.trim() !== '' && Number(quantidade) > 0

  const submit = async () => {
    if (!canSubmit || sigtap == null || cbo == null) return
    setBusy(true)
    setError('')
    try {
      await apiFetch('/api/v1/billing/bpa-consolidado/', {
        method: 'POST',
        body: JSON.stringify({
          competencia: competenciaId,
          sigtap: sigtap.id,
          cbo: cbo.id,
          idade: Number(idade),
          quantidade: Number(quantidade),
        }),
      })
      setSigtap(null)
      setCbo(null)
      setIdade('')
      setQuantidade('1')
      onAdded()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError('Dados inválidos para a linha BPA-C. Verifique os campos.')
      } else {
        setError('Não foi possível adicionar a linha BPA-C. Tente novamente.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-neu-panel p-4">
      <h3 className="mb-3 text-sm font-semibold text-neu-ink">Adicionar BPA-C</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">
            Procedimento (SIGTAP)
          </span>
          <RemoteCombobox<SigtapOption>
            label="Procedimento SIGTAP"
            endpoint="/api/v1/sigtap/"
            queryParam="q"
            value={sigtap}
            getKey={(item) => String(item.id)}
            getLabel={(item) => `${item.code} — ${item.display}`}
            onChange={setSigtap}
            placeholder="Buscar procedimento SIGTAP…"
          />
        </div>
        <div>
          <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">Ocupação (CBO)</span>
          <RemoteCombobox<CboOption>
            label="Ocupação CBO"
            endpoint="/api/v1/terminology/cbo/"
            queryParam="q"
            value={cbo}
            getKey={(item) => item.code}
            getLabel={(item) => `${item.code} — ${item.display}`}
            onChange={setCbo}
            placeholder="Buscar ocupação (CBO)…"
          />
        </div>
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Idade (faixa etária)
          <input
            aria-label="Idade (faixa etária)"
            type="number"
            min={0}
            value={idade}
            onChange={(event) => setIdade(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Quantidade
          <input
            aria-label="Quantidade"
            type="number"
            min={1}
            value={quantidade}
            onChange={(event) => setQuantidade(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
      </div>
      {error && <p className="mt-2 text-xs font-semibold text-red-700">{error}</p>}
      <div className="mt-3">
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit || busy}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          <Plus size={15} />
          {busy ? 'Adicionando…' : 'Adicionar BPA-C'}
        </button>
      </div>
    </div>
  )
}
