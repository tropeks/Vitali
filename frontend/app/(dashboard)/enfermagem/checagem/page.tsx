'use client'

import { useState } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import MarList from '@/components/nursing/MarList'
import BcmaCheckModal from '@/components/nursing/BcmaCheckModal'
import type {
  MarDueItem,
  MarPatient,
  MarPrescription,
} from '@/components/nursing/mar-types'

type ListOr<T> = T[] | { results?: T[] | null }

function asArray<T>(data: ListOr<T>): T[] {
  return Array.isArray(data) ? data : (data.results ?? [])
}

/** Flatten a patient's prescriptions to the due (signed-order) medications. */
function dueItemsFrom(prescriptions: MarPrescription[]): MarDueItem[] {
  return prescriptions
    .filter((rx) => rx.is_signed || rx.status === 'signed' || rx.status === 'active')
    .flatMap((rx) => rx.items ?? [])
}

export default function ChecagemPage() {
  const [query, setQuery] = useState('')
  const [patient, setPatient] = useState<MarPatient | null>(null)
  const [scannedBarcode, setScannedBarcode] = useState('')
  const [dueItems, setDueItems] = useState<MarDueItem[]>([])
  const [administeredIds, setAdministeredIds] = useState<string[]>([])
  const [checking, setChecking] = useState<MarDueItem | null>(null)
  const [loading, setLoading] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    const scanned = query.trim()
    if (!scanned) return

    setLoading(true)
    setError(null)
    setNotFound(false)
    setPatient(null)
    setDueItems([])
    setAdministeredIds([])
    setSearched(true)

    try {
      const params = new URLSearchParams({ search: scanned, ordering: 'full_name' })
      const found = asArray(
        await apiFetch<ListOr<MarPatient>>(`/api/v1/patients/?${params.toString()}`)
      )
      if (found.length === 0) {
        setNotFound(true)
        return
      }
      const p = found[0]
      setPatient(p)
      setScannedBarcode(scanned)

      const rxParams = new URLSearchParams({ patient: p.id })
      const prescriptions = asArray(
        await apiFetch<ListOr<MarPrescription>>(
          `/api/v1/prescriptions/?${rxParams.toString()}`
        )
      )
      setDueItems(dueItemsFrom(prescriptions))
    } catch {
      setError('Erro ao carregar as medicações do paciente.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">MAR · checagem beira-leito</h1>
        <p className="mt-0.5 text-sm text-neu-inkMuted">
          Escaneie a pulseira do paciente, confira as medicações pendentes e execute a checagem
          dos 5 certos (BCMA) antes de administrar.
        </p>
      </div>

      <form
        onSubmit={handleSearch}
        className="flex flex-wrap items-end gap-2 rounded-lg border border-white bg-neu-panel p-4"
      >
        <label className="flex-1 text-sm">
          <span className="mb-1 block font-medium text-neu-ink">
            Código ou prontuário do paciente
          </span>
          <input
            aria-label="Código ou prontuário do paciente"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Escaneie a pulseira ou digite o prontuário"
            className="w-full min-w-[220px] rounded-md border border-slate-300 bg-neu-input px-3 py-2 text-neu-ink"
            autoComplete="off"
          />
        </label>
        <button
          type="submit"
          disabled={loading || query.trim() === ''}
          className="rounded-md bg-neu-brand px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          Buscar paciente
        </button>
      </form>

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {error && (
        <SectionState
          title="Erro ao carregar as medicações do paciente."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {!loading && !error && notFound && (
        <SectionState
          title="Nenhum paciente encontrado para esse código."
          detail="Confira o código escaneado ou o número do prontuário e tente novamente."
          tone="warning"
        />
      )}

      {!loading && !error && patient && (
        <div className="space-y-3">
          <div className="flex items-baseline gap-3">
            <span className="text-lg font-semibold text-neu-ink">{patient.full_name}</span>
            {patient.medical_record_number && (
              <span className="font-mono text-xs text-neu-inkMuted">
                {patient.medical_record_number}
              </span>
            )}
          </div>

          {dueItems.length === 0 ? (
            <SectionState
              title="Nenhuma medicação pendente para este paciente."
              detail="Não há itens de receita assinada aprazados para checagem no momento."
            />
          ) : (
            <MarList items={dueItems} administeredIds={administeredIds} onCheck={setChecking} />
          )}
        </div>
      )}

      {!searched && !loading && (
        <SectionState
          title="Escaneie um paciente para começar."
          detail="A lista de medicações e a checagem beira-leito aparecem após identificar o paciente."
        />
      )}

      {checking && (
        <BcmaCheckModal
          item={checking}
          patientBarcode={scannedBarcode}
          onClose={() => setChecking(null)}
          onRecorded={(item) => {
            setAdministeredIds((prev) =>
              prev.includes(item.id) ? prev : [...prev, item.id]
            )
            setChecking(null)
          }}
        />
      )}
    </PageShell>
  )
}
