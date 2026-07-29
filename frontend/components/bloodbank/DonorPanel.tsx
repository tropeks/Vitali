'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, UserPlus, X } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  ABO_OPTIONS,
  aboRhLabel,
  apiErrorDetail,
  formatDate,
  normalizeList,
  RH_OPTIONS,
  type Abo,
  type BloodDonorDTO,
  type ListResponse,
  type RhFactor,
} from './bloodbank-types'

interface DonorPanelProps {
  canManage: boolean
}

/**
 * Doadores de sangue — GET /api/v1/blood-donors/ list + cadastro
 * (hemoterapia.manage) via POST. Kept lean: name/CPF, ABO/Rh, aptidão.
 */
export default function DonorPanel({ canManage }: DonorPanelProps) {
  const [donors, setDonors] = useState<BloodDonorDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse<BloodDonorDTO> | BloodDonorDTO[]>(
        '/api/v1/blood-donors/'
      )
      setDonors(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-3">
      {canManage && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <UserPlus size={15} aria-hidden />
            Cadastrar doador
          </button>
        </div>
      )}

      {loading ? (
        <SectionState title="Carregando doadores..." detail="Buscando o cadastro de doadores." />
      ) : error ? (
        <SectionState
          title="Erro ao carregar doadores"
          detail="Não foi possível carregar os doadores. Tente novamente."
          tone="critical"
          action={
            <button
              onClick={load}
              className="inline-flex items-center gap-2 text-xs font-semibold text-red-700 hover:underline"
            >
              <RefreshCw size={13} />
              Tentar novamente
            </button>
          }
        />
      ) : donors.length === 0 ? (
        <SectionState
          title="Nenhum doador cadastrado"
          detail="Cadastre doadores para acompanhar o cadastro e a aptidão."
        />
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-neu-panel">
          {donors.map((donor) => (
            <li
              key={donor.id}
              aria-label={`Doador ${donor.full_name}`}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2">
                {donor.abo ? (
                  <span className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-1.5 py-0.5 text-xs font-bold text-red-700">
                    {aboRhLabel(donor.abo, donor.rh_factor)}
                  </span>
                ) : null}
                <span className="font-medium text-neu-ink">{donor.full_name}</span>
                {donor.cpf ? <span className="text-xs text-neu-inkMuted">{donor.cpf}</span> : null}
              </div>
              <div className="flex items-center gap-2 text-xs text-neu-inkMuted">
                {donor.last_donation ? (
                  <span>Última doação {formatDate(donor.last_donation)}</span>
                ) : null}
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${
                    donor.apto
                      ? 'border-green-300 bg-green-50 text-green-800'
                      : 'border-slate-300 bg-slate-100 text-slate-600'
                  }`}
                >
                  {donor.apto ? 'Apto' : 'Inapto'}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {creating && (
        <DonorModal
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            load()
          }}
        />
      )}
    </div>
  )
}

interface DonorModalProps {
  onClose: () => void
  onCreated: () => void
}

function DonorModal({ onClose, onCreated }: DonorModalProps) {
  const [fullName, setFullName] = useState('')
  const [cpf, setCpf] = useState('')
  const [abo, setAbo] = useState<Abo | ''>('')
  const [rhFactor, setRhFactor] = useState<RhFactor | ''>('')
  const [apto, setApto] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!fullName.trim()) {
      setError('Informe o nome do doador.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await apiFetch('/api/v1/blood-donors/', {
        method: 'POST',
        body: JSON.stringify({
          full_name: fullName.trim(),
          cpf: cpf.trim(),
          abo,
          rh_factor: rhFactor,
          apto,
        }),
      })
      onCreated()
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 409)) {
        setError(apiErrorDetail(err.body, 'Não foi possível cadastrar o doador.'))
        return
      }
      setError('Não foi possível cadastrar o doador. Tente novamente.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Cadastrar doador"
    >
      <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white shadow-neu-modal">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="text-base font-semibold text-neu-ink">Cadastrar doador</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <label className="block text-xs font-semibold text-neu-inkSoft">
            Nome completo
            <input
              aria-label="Nome completo"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
            />
          </label>
          <label className="block text-xs font-semibold text-neu-inkSoft">
            CPF (opcional)
            <input
              aria-label="CPF"
              value={cpf}
              onChange={(e) => setCpf(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Grupo ABO
              <select
                aria-label="Grupo ABO do doador"
                value={abo}
                onChange={(e) => setAbo(e.target.value as Abo | '')}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              >
                <option value="">—</option>
                {ABO_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-semibold text-neu-inkSoft">
              Fator Rh
              <select
                aria-label="Fator Rh do doador"
                value={rhFactor}
                onChange={(e) => setRhFactor(e.target.value as RhFactor | '')}
                className="mt-1 w-full rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-sm font-normal text-neu-ink"
              >
                <option value="">—</option>
                {RH_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm text-neu-ink">
            <input type="checkbox" checked={apto} onChange={(e) => setApto(e.target.checked)} />
            Apto a doar
          </label>

          {error && <p className="text-sm font-semibold text-red-700">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-neu-inkSoft hover:bg-slate-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="rounded-lg bg-neu-brand px-3 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? 'Cadastrando...' : 'Cadastrar doador'}
          </button>
        </div>
      </div>
    </div>
  )
}
