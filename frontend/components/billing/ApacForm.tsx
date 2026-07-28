'use client'

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import RemoteCombobox from '@/components/shared/RemoteCombobox'
import type { PatientOption, ProfessionalOption, SigtapOption } from './sus-types'

interface Props {
  competenciaId: number
  onCreated: () => void
  onCancel: () => void
}

/**
 * Criação de uma autorização APAC (alta complexidade): número, validade,
 * procedimento principal (SIGTAP), CID, paciente, profissionais solicitante/
 * executante e valor autorizado. `valor` é client-set (o valor autorizado, não
 * uma derivação pura SIGTAP × qtd).
 */
export default function ApacForm({ competenciaId, onCreated, onCancel }: Props) {
  const [numeroApac, setNumeroApac] = useState('')
  const [validadeInicio, setValidadeInicio] = useState('')
  const [validadeFim, setValidadeFim] = useState('')
  const [procedimento, setProcedimento] = useState<SigtapOption | null>(null)
  const [cid, setCid] = useState('')
  const [patient, setPatient] = useState<PatientOption | null>(null)
  const [solicitante, setSolicitante] = useState<ProfessionalOption | null>(null)
  const [executante, setExecutante] = useState<ProfessionalOption | null>(null)
  const [valor, setValor] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const canSubmit =
    numeroApac.trim() !== '' &&
    validadeInicio !== '' &&
    validadeFim !== '' &&
    procedimento != null &&
    patient != null

  const submit = async () => {
    if (!canSubmit || procedimento == null || patient == null) return
    setBusy(true)
    setError('')
    try {
      await apiFetch('/api/v1/billing/apac-autorizacoes/', {
        method: 'POST',
        body: JSON.stringify({
          competencia: competenciaId,
          numero_apac: numeroApac.trim(),
          validade_inicio: validadeInicio,
          validade_fim: validadeFim,
          procedimento_principal: procedimento.id,
          cid_principal: cid.trim(),
          patient: patient.id,
          professional_solicitante: solicitante?.id ?? null,
          professional_executante: executante?.id ?? null,
          valor: valor.trim() === '' ? '0' : valor,
        }),
      })
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError('Dados inválidos para a APAC. Verifique o número e os campos obrigatórios.')
      } else {
        setError('Não foi possível criar a APAC. Tente novamente.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-neu-panel p-4">
      <h3 className="mb-3 text-sm font-semibold text-neu-ink">Nova APAC</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Número da APAC
          <input
            aria-label="Número da APAC"
            value={numeroApac}
            onChange={(event) => setNumeroApac(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Valor autorizado (R$)
          <input
            aria-label="Valor autorizado (R$)"
            type="number"
            min={0}
            step="0.01"
            value={valor}
            onChange={(event) => setValor(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Início da validade
          <input
            aria-label="Início da validade"
            type="date"
            value={validadeInicio}
            onChange={(event) => setValidadeInicio(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-xs font-semibold text-neu-inkSoft">
          Fim da validade
          <input
            aria-label="Fim da validade"
            type="date"
            value={validadeFim}
            onChange={(event) => setValidadeFim(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <div>
          <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">
            Procedimento principal (SIGTAP)
          </span>
          <RemoteCombobox<SigtapOption>
            label="Procedimento principal"
            endpoint="/api/v1/sigtap/"
            queryParam="q"
            value={procedimento}
            getKey={(item) => String(item.id)}
            getLabel={(item) => `${item.code} — ${item.display}`}
            onChange={setProcedimento}
            placeholder="Buscar procedimento SIGTAP…"
          />
        </div>
        <label className="block text-xs font-semibold text-neu-inkSoft">
          CID-10 principal
          <input
            aria-label="CID-10 principal"
            value={cid}
            onChange={(event) => setCid(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        <div>
          <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">Paciente</span>
          <RemoteCombobox<PatientOption>
            label="Paciente"
            endpoint="/api/v1/patients/"
            queryParam="search"
            value={patient}
            getKey={(item) => item.id}
            getLabel={(item) => item.full_name}
            onChange={setPatient}
            placeholder="Buscar paciente…"
          />
        </div>
        <div>
          <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">
            Profissional solicitante (opcional)
          </span>
          <RemoteCombobox<ProfessionalOption>
            label="Profissional solicitante"
            endpoint="/api/v1/professionals/"
            queryParam="search"
            value={solicitante}
            getKey={(item) => item.id}
            getLabel={(item) => item.user_name ?? item.id}
            onChange={setSolicitante}
            placeholder="Buscar profissional…"
          />
        </div>
        <div>
          <span className="mb-1 block text-xs font-semibold text-neu-inkSoft">
            Profissional executante (opcional)
          </span>
          <RemoteCombobox<ProfessionalOption>
            label="Profissional executante"
            endpoint="/api/v1/professionals/"
            queryParam="search"
            value={executante}
            getKey={(item) => item.id}
            getLabel={(item) => item.user_name ?? item.id}
            onChange={setExecutante}
            placeholder="Buscar profissional…"
          />
        </div>
      </div>
      {error && <p className="mt-2 text-xs font-semibold text-red-700">{error}</p>}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit || busy}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
        >
          <Plus size={15} />
          {busy ? 'Criando…' : 'Criar APAC'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm font-semibold text-slate-500 hover:underline"
        >
          Cancelar
        </button>
      </div>
    </div>
  )
}
