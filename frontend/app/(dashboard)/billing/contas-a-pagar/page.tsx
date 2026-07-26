'use client'

import { useCallback, useEffect, useState } from 'react'
import { PageShell, SectionState } from '@/components/shared'
import { apiFetch } from '@/lib/api'
import { apiErrorMessage, listResults, type ListResponse } from '@/lib/admin'
import PayableTable from '@/components/billing/PayableTable'
import PayableCreateModal from '@/components/billing/PayableCreateModal'
import type { Payable } from '@/components/billing/financeFormat'

export default function ContasAPagarPage() {
  const [payables, setPayables] = useState<Payable[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<ListResponse<Payable>>('/api/v1/billing/payables/')
      setPayables(listResults(data))
    } catch (e) {
      setError(apiErrorMessage(e, 'Não foi possível carregar as contas a pagar.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const runAction = useCallback(async (payable: Payable, verb: 'approve' | 'pay') => {
    setBusyId(payable.id)
    setActionError(null)
    try {
      const updated = await apiFetch<Payable>(`/api/v1/billing/payables/${payable.id}/${verb}/`, {
        method: 'POST',
      })
      setPayables((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
    } catch (e) {
      setActionError(apiErrorMessage(e, 'Não foi possível atualizar a conta.'))
    } finally {
      setBusyId(null)
    }
  }, [])

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Contas a pagar</h1>
          <p className="mt-1 text-sm text-neu-inkSoft">
            Aprovação e pagamento com segregação de funções (quem cria não aprova).
          </p>
        </div>
        <button className="neu-button-primary" onClick={() => setCreating(true)}>Nova conta</button>
      </div>

      {error && <SectionState title="Contas indisponíveis" detail={error} tone="critical" />}
      {actionError && <SectionState title="Ação não concluída" detail={actionError} tone="warning" />}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando…</p>}

      {!loading && !error && payables.length === 0 && (
        <SectionState
          title="Nenhuma conta a pagar cadastrada."
          detail="Cadastre uma conta para iniciar o fluxo de aprovação e pagamento."
        />
      )}

      {!loading && !error && payables.length > 0 && (
        <PayableTable
          payables={payables}
          busyId={busyId}
          onApprove={(p) => void runAction(p, 'approve')}
          onPay={(p) => void runAction(p, 'pay')}
        />
      )}

      {creating && (
        <PayableCreateModal
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setPayables((prev) => [created, ...prev])
            setCreating(false)
          }}
        />
      )}
    </PageShell>
  )
}
