'use client'

import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { SectionState, StatusBadge } from '@/components/shared'
import AihList from './AihList'
import ApacList from './ApacList'
import BpaConsolidadoForm from './BpaConsolidadoForm'
import SusProducaoPanel from './SusProducaoPanel'
import {
  formatBRL,
  normalizeList,
  susStatusMeta,
  sumValores,
  type AihAutorizacaoLine,
  type ApacAutorizacaoLine,
  type BpaConsolidadoLine,
  type BpaIndividualizadoLine,
  type ListResponse,
  type SusCompetencia,
} from './sus-types'

interface Props {
  competenciaId: number
  canWrite: boolean
  canExport: boolean
  onBack: () => void
}

/**
 * Detalhe da competência SUS: cabeçalho + badge de situação, painel de produção
 * (KPIs + ações do ciclo), listas de BPA-I (read-only, gerado), BPA-C (com
 * entrada manual) e APAC (com criação). Fonte única: o detalhe busca as quatro
 * coleções; os formulários disparam `reload` para recalcular KPIs + listas.
 */
export default function SusCompetenciaDetail({
  competenciaId,
  canWrite,
  canExport,
  onBack,
}: Props) {
  const [competencia, setCompetencia] = useState<SusCompetencia | null>(null)
  const [bpaI, setBpaI] = useState<BpaIndividualizadoLine[]>([])
  const [bpaC, setBpaC] = useState<BpaConsolidadoLine[]>([])
  const [apacs, setApacs] = useState<ApacAutorizacaoLine[]>([])
  const [aihs, setAihs] = useState<AihAutorizacaoLine[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const [competenciaData, bpaIData, bpaCData, apacData, aihData] = await Promise.all([
        apiFetch<SusCompetencia>(`/api/v1/billing/sus-competencias/${competenciaId}/`),
        apiFetch<ListResponse<BpaIndividualizadoLine> | BpaIndividualizadoLine[]>(
          `/api/v1/billing/bpa-individualizado/?competencia=${competenciaId}`,
        ),
        apiFetch<ListResponse<BpaConsolidadoLine> | BpaConsolidadoLine[]>(
          `/api/v1/billing/bpa-consolidado/?competencia=${competenciaId}`,
        ),
        apiFetch<ListResponse<ApacAutorizacaoLine> | ApacAutorizacaoLine[]>(
          `/api/v1/billing/apac-autorizacoes/?competencia=${competenciaId}`,
        ),
        apiFetch<ListResponse<AihAutorizacaoLine> | AihAutorizacaoLine[]>(
          `/api/v1/billing/aih-autorizacoes/?competencia=${competenciaId}`,
        ),
      ])
      setCompetencia(competenciaData)
      setBpaI(normalizeList(bpaIData))
      setBpaC(normalizeList(bpaCData))
      setApacs(normalizeList(apacData))
      setAihs(normalizeList(aihData))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [competenciaId])

  useEffect(() => {
    load()
  }, [load])

  const backButton = (
    <button
      type="button"
      onClick={onBack}
      className="inline-flex items-center gap-1 text-sm font-semibold text-neu-brand hover:underline"
    >
      <ArrowLeft size={15} />
      Voltar às competências
    </button>
  )

  if (loading) {
    return (
      <div className="space-y-4">
        {backButton}
        <SectionState
          title="Carregando competência…"
          detail="Buscando produção (BPA-I / BPA-C / APAC) da competência."
        />
      </div>
    )
  }

  if (error || !competencia) {
    return (
      <div className="space-y-4">
        {backButton}
        <SectionState
          title="Erro ao carregar competência"
          detail="Não foi possível carregar o detalhe da competência. Tente novamente."
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
      </div>
    )
  }

  const isAberta = competencia.status === 'aberta'
  const totalValor = sumValores(bpaI) + sumValores(bpaC) + sumValores(apacs) + sumValores(aihs)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          {backButton}
          <h2 className="font-mono text-xl font-semibold text-neu-ink">
            Competência {competencia.competencia}
          </h2>
        </div>
        <StatusBadge meta={susStatusMeta(competencia.status)} />
      </div>

      <SusProducaoPanel
        competencia={competencia}
        bpaICount={bpaI.length}
        bpaCCount={bpaC.length}
        apacCount={apacs.length}
        aihCount={aihs.length}
        totalValor={totalValor}
        canWrite={canWrite}
        canExport={canExport}
        onChanged={load}
      />

      {/* BPA-I — read-only (gerado pelo bridge) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-neu-ink">BPA-I — individualizado ({bpaI.length})</h2>
        {bpaI.length === 0 ? (
          <SectionState
            title="Nenhum BPA-I"
            detail="Gere a produção da competência para criar as linhas BPA-I individualizadas."
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-neu-panel">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100">
                <tr>
                  {['SIGTAP', 'CNS', 'CID', 'Qtd.', 'Valor'].map((header) => (
                    <th
                      key={header}
                      className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {bpaI.map((line) => (
                  <tr key={line.id}>
                    <td className="px-4 py-3 font-mono text-neu-ink">{line.sigtap}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{line.cns || '—'}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{line.cid || '—'}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{line.quantidade}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{formatBRL(line.valor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* BPA-C — manual */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-neu-ink">BPA-C — consolidado ({bpaC.length})</h2>
        {canWrite && isAberta && (
          <BpaConsolidadoForm competenciaId={competencia.id} onAdded={load} />
        )}
        {bpaC.length === 0 ? (
          <SectionState
            title="Nenhum BPA-C"
            detail="Adicione linhas BPA-C manuais (procedimento × CBO × idade × quantidade)."
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-neu-panel">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100">
                <tr>
                  {['SIGTAP', 'CBO', 'Idade', 'Qtd.', 'Valor'].map((header) => (
                    <th
                      key={header}
                      className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {bpaC.map((line) => (
                  <tr key={line.id}>
                    <td className="px-4 py-3 font-mono text-neu-ink">{line.sigtap}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{line.cbo}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{line.idade}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{line.quantidade}</td>
                    <td className="px-4 py-3 text-neu-inkSoft">{formatBRL(line.valor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* APAC */}
      <ApacList
        competenciaId={competencia.id}
        apacs={apacs}
        canWrite={canWrite}
        aberta={isAberta}
        onChanged={load}
      />

      {/* AIH — internação (gerada pelo bridge; reconciliação/rejeição aqui) */}
      <AihList aihs={aihs} canWrite={canWrite} onChanged={load} />
    </div>
  )
}
