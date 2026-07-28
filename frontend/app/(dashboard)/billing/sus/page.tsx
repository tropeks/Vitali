'use client'

import { useMemo, useState } from 'react'
import { hasPermission } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { PageShell, SectionState } from '@/components/shared'
import SusCompetenciaList from '@/components/billing/SusCompetenciaList'
import SusCompetenciaDetail from '@/components/billing/SusCompetenciaDetail'

/**
 * Faturamento SUS (S4) — painel BPA/APAC.
 *
 * Lista de competências (filtro establishment/status + criação) e, ao
 * selecionar, o detalhe da competência (KPIs, produção BPA-I/BPA-C/APAC e ações
 * do ciclo gerar/fechar/exportar). A página exige `sus.read`; a escrita e a
 * exportação são gated por `sus.write` / `sus.export`. O backend permanece a
 * barreira real — esconder um controle nunca é controle de acesso.
 */
export default function FaturamentoSusPage() {
  const canRead = useMemo(() => hasPermission(PERMISSIONS.SUS_READ), [])
  const canWrite = useMemo(() => hasPermission(PERMISSIONS.SUS_WRITE), [])
  const canExport = useMemo(() => hasPermission(PERMISSIONS.SUS_EXPORT), [])

  const [selected, setSelected] = useState<number | null>(null)

  if (!canRead) {
    return (
      <PageShell variant="operational">
        <SectionState
          title="Sem acesso ao Faturamento SUS"
          detail="Você não tem permissão para visualizar o faturamento SUS (sus.read)."
          tone="warning"
        />
      </PageShell>
    )
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Faturamento SUS</h1>
        <p className="mt-0.5 text-sm text-neu-inkMuted">
          Competências, produção ambulatorial (BPA-I / BPA-C) e autorizações APAC. Gere a
          produção, feche a competência e exporte a remessa DATASUS conforme suas permissões.
        </p>
      </div>

      {selected == null ? (
        <SusCompetenciaList canWrite={canWrite} onSelect={setSelected} />
      ) : (
        <SusCompetenciaDetail
          competenciaId={selected}
          canWrite={canWrite}
          canExport={canExport}
          onBack={() => setSelected(null)}
        />
      )}
    </PageShell>
  )
}
