'use client'

import { useState } from 'react'
import { Download, FileCog, Lock, Play } from 'lucide-react'
import { apiFetch, ApiError } from '@/lib/api'
import { KpiTile } from '@/components/shared'
import {
  downloadTextFile,
  formatBRL,
  type ExportarResult,
  type GerarProducaoResult,
  type SusCompetencia,
} from './sus-types'

interface Props {
  competencia: SusCompetencia
  bpaICount: number
  bpaCCount: number
  apacCount: number
  totalValor: number
  /** `sus.write` — gates gerar-produção + fechar. */
  canWrite: boolean
  /** `sus.export` — gates exportar remessa. */
  canExport: boolean
  /** Called after any cycle action that changed server state. */
  onChanged: () => void
}

/**
 * Painel de produção da competência: KPIs (nº BPA-I / BPA-C / APAC, valor total)
 * + ações do ciclo (gerar produção, fechar, exportar remessa). Cada ação é gated
 * por permissão e trata o 409 do backend (competência em situação incompatível).
 * Exportar baixa os `.txt` da remessa client-side (Blob + `<a download>`).
 */
export default function SusProducaoPanel({
  competencia,
  bpaICount,
  bpaCCount,
  apacCount,
  totalValor,
  canWrite,
  canExport,
  onChanged,
}: Props) {
  const isAberta = competencia.status === 'aberta'
  const isFechada = competencia.status === 'fechada'

  const [gerarBusy, setGerarBusy] = useState(false)
  const [gerarResult, setGerarResult] = useState<GerarProducaoResult | null>(null)
  const [gerarError, setGerarError] = useState('')

  const [fecharBusy, setFecharBusy] = useState(false)
  const [fecharError, setFecharError] = useState('')

  const [exportBusy, setExportBusy] = useState(false)
  const [exportError, setExportError] = useState('')

  const gerarProducao = async () => {
    setGerarBusy(true)
    setGerarError('')
    setGerarResult(null)
    try {
      const result = await apiFetch<GerarProducaoResult>(
        `/api/v1/billing/sus-competencias/${competencia.id}/gerar-producao/`,
        { method: 'POST' },
      )
      setGerarResult(result)
      onChanged()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setGerarError(
          err.body?.detail ??
            'Competência fechada/exportada — não é possível gerar produção.',
        )
      } else {
        setGerarError('Não foi possível gerar a produção. Tente novamente.')
      }
    } finally {
      setGerarBusy(false)
    }
  }

  const fecharCompetencia = async () => {
    setFecharBusy(true)
    setFecharError('')
    try {
      await apiFetch(`/api/v1/billing/sus-competencias/${competencia.id}/fechar/`, {
        method: 'POST',
      })
      onChanged()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setFecharError(err.body?.detail ?? 'Competência já está fechada/exportada.')
      } else {
        setFecharError('Não foi possível fechar a competência. Tente novamente.')
      }
    } finally {
      setFecharBusy(false)
    }
  }

  const exportarRemessa = async () => {
    setExportBusy(true)
    setExportError('')
    try {
      const result = await apiFetch<ExportarResult>(
        `/api/v1/billing/sus-competencias/${competencia.id}/exportar/`,
        { method: 'POST' },
      )
      downloadTextFile(result.filename_bpa, result.remessa_bpa)
      downloadTextFile(result.filename_apac, result.remessa_apac)
      onChanged()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setExportError(err.body?.detail ?? 'Feche a competência antes de exportar a remessa.')
      } else {
        setExportError('Não foi possível exportar a remessa. Tente novamente.')
      }
    } finally {
      setExportBusy(false)
    }
  }

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile label="BPA-I (gerado)" value={bpaICount} />
        <KpiTile label="BPA-C (manual)" value={bpaCCount} />
        <KpiTile label="APAC" value={apacCount} />
        <KpiTile label="Valor total da produção" value={formatBRL(totalValor)} tone="info" />
      </div>

      {(canWrite || canExport) && (
        <div className="rounded-lg border border-slate-200 bg-neu-panel p-4">
          <h3 className="mb-3 text-sm font-semibold text-neu-ink">Ações do ciclo</h3>
          <div className="flex flex-wrap items-center gap-2">
            {canWrite && (
              <button
                type="button"
                onClick={gerarProducao}
                disabled={gerarBusy || !isAberta}
                title={!isAberta ? 'Só é possível gerar produção com a competência aberta.' : undefined}
                className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-60"
              >
                <Play size={15} />
                {gerarBusy ? 'Gerando…' : 'Gerar produção'}
              </button>
            )}
            {canWrite && (
              <button
                type="button"
                onClick={fecharCompetencia}
                disabled={fecharBusy || !isAberta}
                title={!isAberta ? 'A competência não está aberta.' : undefined}
                className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-700 hover:bg-amber-100 disabled:opacity-60"
              >
                <Lock size={15} />
                {fecharBusy ? 'Fechando…' : 'Fechar competência'}
              </button>
            )}
            {canExport && (
              <button
                type="button"
                onClick={exportarRemessa}
                disabled={exportBusy || !isFechada}
                title={
                  !isFechada ? 'Feche a competência antes de exportar a remessa.' : undefined
                }
                className="inline-flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm font-semibold text-green-700 hover:bg-green-100 disabled:opacity-60"
              >
                <Download size={15} />
                {exportBusy ? 'Exportando…' : 'Exportar remessa'}
              </button>
            )}
          </div>

          {gerarResult && (
            <p className="mt-3 flex items-center gap-2 text-xs font-semibold text-blue-700">
              <FileCog size={14} />
              <span>
                {`Produção gerada: ${gerarResult.bpa_i_count} BPA-I · ${formatBRL(gerarResult.total_valor)}`}
              </span>
            </p>
          )}
          {gerarError && <p className="mt-2 text-xs font-semibold text-red-700">{gerarError}</p>}
          {fecharError && <p className="mt-2 text-xs font-semibold text-red-700">{fecharError}</p>}
          {exportError && <p className="mt-2 text-xs font-semibold text-red-700">{exportError}</p>}
        </div>
      )}
    </section>
  )
}
