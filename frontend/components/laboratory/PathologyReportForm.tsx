'use client'

import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import { PATHOLOGY_STATUS_OPTIONS } from './especializado-types'

interface Props {
  orderItemId: string
  onCreated: () => void
  onCancel: () => void
}

interface TermOption {
  code: string
  display: string
}
interface SpecimenRow {
  label: string
  site: string
  blocks_count: string
}

/**
 * Lançar laudo anatomopatológico (emr.write): diagnóstico + macro/microscopia +
 * CID-O (topografia via catálogo CID-10, morfologia via catálogo CID-O, ambos
 * autocomplete governado) + espécimes, tudo em um POST /pathology-reports/
 * (cid_o_*_code reconciliados + specimens_input nested).
 */
export default function PathologyReportForm({ orderItemId, onCreated, onCancel }: Props) {
  const [clinicalHistory, setClinicalHistory] = useState('')
  const [macroscopy, setMacroscopy] = useState('')
  const [microscopy, setMicroscopy] = useState('')
  const [diagnosis, setDiagnosis] = useState('')
  const [status, setStatus] = useState('pendente')
  const [topography, setTopography] = useState<TermOption | null>(null)
  const [morphology, setMorphology] = useState<TermOption | null>(null)
  const [specimens, setSpecimens] = useState<SpecimenRow[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const inputCls =
    'w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm text-neu-ink'

  async function submit() {
    setSubmitting(true)
    setError(null)
    const specimens_input = specimens
      .filter((s) => s.label.trim())
      .map((s) => ({
        label: s.label.trim(),
        site: s.site.trim(),
        blocks_count: Number(s.blocks_count) || 0,
      }))
    try {
      await apiFetch('/api/v1/pathology-reports/', {
        method: 'POST',
        body: JSON.stringify({
          order_item: orderItemId,
          clinical_history: clinicalHistory.trim(),
          macroscopy: macroscopy.trim(),
          microscopy: microscopy.trim(),
          diagnosis: diagnosis.trim(),
          status,
          cid_o_topography_code: topography?.code ?? '',
          cid_o_morphology_code: morphology?.code ?? '',
          specimens_input,
        }),
      })
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
        setError('Não foi possível salvar — talvez já exista um laudo para este pedido.')
        return
      }
      setError('Não foi possível salvar o laudo. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-blue-200 bg-blue-50/40 p-4">
      <h4 className="text-sm font-semibold text-neu-ink">Novo laudo anatomopatológico</h4>

      <label className="block text-sm">
        <span className="mb-1 block font-medium text-neu-ink">História clínica</span>
        <textarea value={clinicalHistory} onChange={(e) => setClinicalHistory(e.target.value)} rows={2} className={inputCls} />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Macroscopia</span>
          <textarea value={macroscopy} onChange={(e) => setMacroscopy(e.target.value)} rows={2} className={inputCls} />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-neu-ink">Microscopia</span>
          <textarea value={microscopy} onChange={(e) => setMicroscopy(e.target.value)} rows={2} className={inputCls} />
        </label>
      </div>
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-neu-ink">Diagnóstico</span>
        <textarea value={diagnosis} onChange={(e) => setDiagnosis(e.target.value)} rows={2} className={inputCls} />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <RemoteCombobox<TermOption>
          label="CID-O topografia (CID-10)"
          endpoint="/api/v1/terminology/cid10/"
          queryParam="q"
          value={topography}
          getKey={(o) => o.code}
          getLabel={(o) => `${o.code} — ${o.display}`}
          onChange={setTopography}
          placeholder="Buscar topografia (ex.: C50)"
        />
        <RemoteCombobox<TermOption>
          label="CID-O morfologia"
          endpoint="/api/v1/terminology/cid_o/"
          queryParam="q"
          value={morphology}
          getKey={(o) => o.code}
          getLabel={(o) => `${o.code} — ${o.display}`}
          onChange={setMorphology}
          placeholder="Buscar morfologia (ex.: 8500)"
        />
      </div>

      <label className="block text-sm sm:w-56">
        <span className="mb-1 block font-medium text-neu-ink">Situação do laudo</span>
        <select aria-label="Situação do laudo" value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls}>
          {PATHOLOGY_STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <div className="space-y-2">
        <p className="text-sm font-medium text-neu-ink">Espécimes</p>
        {specimens.map((s, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              aria-label={`Espécime ${i + 1} rótulo`}
              value={s.label}
              onChange={(e) => setSpecimens((p) => p.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
              className="w-24 rounded-md border border-slate-300 bg-neu-input px-2 py-2 text-sm"
              placeholder="Rótulo"
            />
            <input
              aria-label={`Espécime ${i + 1} sítio`}
              value={s.site}
              onChange={(e) => setSpecimens((p) => p.map((x, j) => (j === i ? { ...x, site: e.target.value } : x)))}
              className={inputCls}
              placeholder="Sítio"
            />
            <input
              aria-label={`Espécime ${i + 1} blocos`}
              value={s.blocks_count}
              onChange={(e) => setSpecimens((p) => p.map((x, j) => (j === i ? { ...x, blocks_count: e.target.value } : x)))}
              className="w-20 rounded-md border border-slate-300 bg-neu-input px-2 py-2 text-sm"
              placeholder="Blocos"
              inputMode="numeric"
            />
            <button
              type="button"
              aria-label={`Remover espécime ${i + 1}`}
              onClick={() => setSpecimens((p) => p.filter((_, j) => j !== i))}
              className="text-red-600 hover:text-red-800"
            >
              <Trash2 size={16} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setSpecimens((p) => [...p, { label: '', site: '', blocks_count: '0' }])}
          className="inline-flex items-center gap-1 text-sm font-semibold text-blue-700 hover:underline"
        >
          <Plus size={15} /> Adicionar espécime
        </button>
      </div>

      {error && <p className="text-sm font-semibold text-red-700">{error}</p>}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-neu-inkSoft hover:bg-neu-panel"
        >
          Cancelar
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={submitting}
          className="rounded-md bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? 'Salvando...' : 'Salvar laudo'}
        </button>
      </div>
    </div>
  )
}
