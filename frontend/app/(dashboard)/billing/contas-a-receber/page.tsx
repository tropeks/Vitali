'use client'

import { useCallback, useEffect, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults, type ListResponse } from '@/lib/admin'
import ReceivableTable from '@/components/billing/ReceivableTable'
import type { Receivable } from '@/components/billing/financeFormat'

export default function ContasAReceberPage() {
  const [receivables, setReceivables] = useState<Receivable[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<ListResponse<Receivable>>('/api/v1/billing/receivables/')
      setReceivables(listResults(data))
    } catch (e) {
      setError(apiErrorMessage(e, 'Não foi possível carregar as contas a receber.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const markReceived = useCallback(async (receivable: Receivable) => {
    setBusyId(receivable.id)
    setActionError(null)
    try {
      const updated = await apiFetch<Receivable>(
        `/api/v1/billing/receivables/${receivable.id}/mark_received/`,
        { method: 'POST' }
      )
      setReceivables((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
    } catch (e) {
      setActionError(apiErrorMessage(e, 'Não foi possível dar baixa na conta.'))
    } finally {
      setBusyId(null)
    }
  }, [])

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-neu-ink">Contas a receber</h1>
        <p className="mt-1 text-sm text-neu-inkSoft">
          Recebíveis por paciente e convênio — dê baixa ao confirmar o recebimento.
        </p>
      </div>

      {error && <SectionState title="Contas indisponíveis" detail={error} tone="critical" />}
      {actionError && <SectionState title="Baixa não concluída" detail={actionError} tone="warning" />}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando…</p>}

      {!loading && !error && receivables.length === 0 && (
        <SectionState
          title="Nenhuma conta a receber cadastrada."
          detail="Recebíveis surgem de guias TISS, atendimentos particulares, pacotes ou cobranças PIX."
        />
      )}

      {!loading && !error && receivables.length > 0 && (
        <ReceivableTable
          receivables={receivables}
          busyId={busyId}
          onMarkReceived={(r) => void markReceived(r)}
        />
      )}
    </PageShell>
  )
}
