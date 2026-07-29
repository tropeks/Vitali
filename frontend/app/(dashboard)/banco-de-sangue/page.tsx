'use client'

import { useMemo, useState } from 'react'
import { hasPermission } from '@/lib/auth'
import { PERMISSIONS } from '@/lib/permissions'
import { PageShell, SectionState } from '@/components/shared'
import BloodStockBoard from '@/components/bloodbank/BloodStockBoard'
import TransfusionRequestQueue from '@/components/bloodbank/TransfusionRequestQueue'
import DonorPanel from '@/components/bloodbank/DonorPanel'

type Tab = 'estoque' | 'requisicoes' | 'doadores'

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'estoque', label: 'Estoque' },
  { id: 'requisicoes', label: 'Requisições' },
  { id: 'doadores', label: 'Doadores' },
]

/**
 * H5 — Banco de Sangue / Agência Transfusional.
 *
 * Estoque de hemocomponentes (bolsas + KPIs + entrada/sorologia), fila de
 * requisições transfusionais (reservar/liberar/cancelar + crossmatch) e cadastro
 * de doadores. Everything reads `hemoterapia.read`; entrada de bolsa + triagem +
 * as ações de agência exigem `hemoterapia.manage`; criar requisição exige
 * `hemoterapia.request`.
 */
export default function BancoDeSanguePage() {
  const canRead = useMemo(() => hasPermission(PERMISSIONS.HEMOTERAPIA_READ), [])
  const canManage = useMemo(() => hasPermission(PERMISSIONS.HEMOTERAPIA_MANAGE), [])
  const canRequest = useMemo(() => hasPermission(PERMISSIONS.HEMOTERAPIA_REQUEST), [])
  const [tab, setTab] = useState<Tab>('estoque')

  if (!canRead) {
    return (
      <PageShell variant="operational">
        <SectionState
          title="Sem acesso ao banco de sangue"
          detail="Você não tem permissão para visualizar a agência transfusional (hemoterapia.read)."
          tone="warning"
        />
      </PageShell>
    )
  }

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Banco de Sangue</h1>
        <p className="mt-0.5 text-sm text-neu-inkMuted">
          Agência transfusional: estoque de hemocomponentes, triagem sorológica (RDC 34),
          requisições transfusionais e doadores.
        </p>
      </div>

      <div role="tablist" aria-label="Seções do banco de sangue" className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg border px-3 py-1.5 text-sm font-semibold ${
              tab === t.id
                ? 'border-neu-brand bg-blue-50 text-neu-brand'
                : 'border-slate-200 text-neu-inkSoft hover:bg-slate-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'estoque' && (
        <section aria-label="Estoque de hemocomponentes">
          <BloodStockBoard canManage={canManage} />
        </section>
      )}
      {tab === 'requisicoes' && (
        <section aria-label="Requisições transfusionais">
          <TransfusionRequestQueue canManage={canManage} canRequest={canRequest} />
        </section>
      )}
      {tab === 'doadores' && (
        <section aria-label="Doadores de sangue">
          <DonorPanel canManage={canManage} />
        </section>
      )}
    </PageShell>
  )
}
