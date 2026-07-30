'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState } from '@/components/shared'
import {
  formatDate,
  normalizeList,
  pathologyStatusMeta,
  type ListResponse,
  type PathologyReport,
} from './especializado-types'

interface Props {
  patientId: string
  /** `emr.read` — gates the read-only pathology surface. */
  canRead: boolean
}

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">{label}</p>
      <p className="whitespace-pre-wrap text-sm text-neu-ink">{value}</p>
    </div>
  )
}

/**
 * Anatomia patológica (AP1) — leitura no prontuário do paciente. Consome
 * GET /api/v1/pathology-reports/?patient= (laudo + espécimes aninhados) e
 * renderiza cada laudo com status, diagnóstico, CID-O e os espécimes. Read-only;
 * o backend enforça emr.read.
 */
export default function PathologyPanel({ patientId, canRead }: Props) {
  const [reports, setReports] = useState<PathologyReport[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    if (!patientId || !canRead) return
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ListResponse<PathologyReport> | PathologyReport[]>(
        `/api/v1/pathology-reports/?patient=${patientId}`,
      )
      setReports(normalizeList(data))
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
        title="Sem acesso à anatomia patológica"
        detail="Você não tem permissão para visualizar os laudos anatomopatológicos (emr.read)."
        tone="warning"
      />
    )
  }

  if (loading) {
    return <SectionState title="Carregando laudos..." detail="Buscando laudos anatomopatológicos." />
  }

  if (error) {
    return (
      <SectionState
        title="Erro ao carregar laudos"
        detail="Não foi possível carregar os laudos. Tente novamente."
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

  if (reports.length === 0) {
    return (
      <SectionState
        title="Nenhum laudo anatomopatológico"
        detail="Este paciente não tem laudos de anatomia patológica registrados."
      />
    )
  }

  return (
    <div className="space-y-4">
      {reports.map((report) => {
        const meta = pathologyStatusMeta(report.status)
        return (
          <article
            key={report.id}
            className="space-y-3 rounded-lg border border-slate-200 bg-neu-panel p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.badgeClass}`}
                >
                  {meta.label}
                </span>
                {report.report_number && (
                  <span className="font-mono text-sm text-neu-ink">{report.report_number}</span>
                )}
              </div>
              <span className="text-xs text-neu-inkMuted">
                Liberado: {formatDate(report.reported_at)}
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="História clínica" value={report.clinical_history} />
              <Field label="Macroscopia" value={report.macroscopy} />
              <Field label="Microscopia" value={report.microscopy} />
              <Field label="Imuno-histoquímica" value={report.immunohistochemistry} />
              <Field label="Diagnóstico" value={report.diagnosis} />
              <div className="flex flex-wrap gap-4">
                {report.cid_o_topography && (
                  <Field label="CID-O topografia" value={report.cid_o_topography} />
                )}
                {report.cid_o_morphology && (
                  <Field label="CID-O morfologia" value={report.cid_o_morphology} />
                )}
              </div>
            </div>

            {report.specimens.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted">
                  Espécimes ({report.specimens.length})
                </p>
                <ul className="space-y-1">
                  {report.specimens.map((spec) => (
                    <li key={spec.id} className="text-sm text-neu-inkSoft">
                      <span className="font-semibold text-neu-ink">{spec.label}</span>
                      {spec.site ? ` — ${spec.site}` : ''}
                      {spec.blocks_count > 0 ? ` (${spec.blocks_count} bloco(s))` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
