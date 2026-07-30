'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  antibiogramMeta,
  cultureResultMeta,
  formatDate,
  normalizeList,
  type ListResponse,
  type MicrobiologyResult,
} from './especializado-types'

interface Props {
  patientId: string
  /** `emr.read` — gates the read-only microbiology surface. */
  canRead: boolean
}

/**
 * Microbiologia estruturada (MB1) — leitura no prontuário do paciente. Consome
 * GET /api/v1/microbiology-results/?patient= (árvore aninhada
 * result→organisms→antibiogram) e renderiza cada cultura com os organismos
 * isolados e o antibiograma como badges S/I/R (verde/âmbar/vermelho). Read-only;
 * o backend enforça emr.read.
 */
export default function MicrobiologyPanel({ patientId, canRead }: Props) {
  const [results, setResults] = useState<MicrobiologyResult[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    if (!patientId || !canRead) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse<MicrobiologyResult> | MicrobiologyResult[]>(
        `/api/v1/microbiology-results/?patient=${patientId}`,
      )
      setResults(normalizeList(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [patientId, canRead])

  useEffect(() => {
    load()
  }, [load])

  if (!canRead) {
    return (
      <SectionState
        title="Sem acesso à microbiologia"
        detail="Você não tem permissão para visualizar os resultados de microbiologia (emr.read)."
        tone="warning"
      />
    )
  }

  if (loading) {
    return <SectionState title="Carregando microbiologia..." detail="Buscando culturas e antibiogramas." />
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar microbiologia"
        detail="Não foi possível carregar os resultados. Tente novamente."
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
    )
  }

  if (results.length === 0) {
    return (
      <SectionState
        title="Nenhum resultado de microbiologia"
        detail="Este paciente não tem culturas microbiológicas registradas."
      />
    )
  }

  return (
    <div className="space-y-4">
      {results.map((result) => {
        const meta = cultureResultMeta(result.culture_result)
        return (
          <article
            key={result.id}
            className="space-y-3 rounded-lg border border-slate-200 bg-neu-panel p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}
                >
                  {meta.label}
                </span>
                {result.specimen && (
                  <span className="text-sm font-medium text-neu-ink">{result.specimen}</span>
                )}
              </div>
              <span className="text-xs text-neu-inkMuted">
                Coleta: {formatDate(result.collected_at)}
              </span>
            </div>

            {result.gram_stain && (
              <p className="text-sm text-neu-inkSoft">
                <span className="font-medium text-neu-ink">Gram:</span> {result.gram_stain}
              </p>
            )}

            {result.organisms.length === 0 ? (
              <p className="text-sm text-neu-inkMuted">Sem organismos isolados.</p>
            ) : (
              <div className="space-y-3">
                {result.organisms.map((org) => (
                  <div key={org.id} className="rounded-md border border-slate-100 p-3">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-semibold text-neu-ink">{org.organism_name}</span>
                      {org.colony_count && (
                        <span className="text-xs text-neu-inkMuted">{org.colony_count}</span>
                      )}
                      {!org.is_significant && (
                        <span className="text-xs italic text-neu-inkMuted">(não significativo)</span>
                      )}
                    </div>
                    {org.antibiogram.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {org.antibiogram.map((abx) => {
                          const abxMeta = antibiogramMeta(abx.interpretation)
                          return (
                            <span
                              key={abx.id}
                              title={abx.mic_value ? `CIM: ${abx.mic_value}` : undefined}
                              className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${abxMeta.badgeClass}`}
                            >
                              <span className="text-neu-inkSoft">{abx.antibiotic}</span>
                              <span className="font-bold">{abxMeta.label}</span>
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
