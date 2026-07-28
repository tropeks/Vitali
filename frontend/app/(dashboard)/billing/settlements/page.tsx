'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState, Button } from '@/components/shared'
import SettlementList from '@/components/billing/SettlementList'
import SettlementDecideModal, {
  type SettlementAction,
} from '@/components/billing/SettlementDecideModal'
import SettlementCreateModal from '@/components/billing/SettlementCreateModal'
import type { Settlement } from '@/components/billing/SettlementRow'

// Repasse a terceiros (professional settlements). Lives under billing/ which is
// already gated by ModuleGate module="billing"; billing perms (Faturista/Admin)
// are enforced server-side. Maker-checker lifecycle: draft → approved → paid,
// driven per row through the approve/pay actions.

type ListPayload = Settlement[] | { results: Settlement[]; count?: number }

interface DecideTarget {
  settlement: Settlement
  action: SettlementAction
}

export default function SettlementsPage() {
  const [settlements, setSettlements] = useState<Settlement[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deciding, setDeciding] = useState<DecideTarget | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<ListPayload>('/api/v1/billing/settlements/')
      setSettlements(Array.isArray(data) ? data : data.results ?? [])
    } catch {
      setError('Erro ao carregar repasses.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const applyUpdate = (updated: Settlement) => {
    setSettlements((previous) => previous.map((s) => (s.id === updated.id ? updated : s)))
    setDeciding(null)
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Repasses a terceiros</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Repasses de honorários aos prestadores, com fluxo de aprovação e pagamento.
          </p>
        </div>
        <Button type="button" variant="primary" onClick={() => setCreating(true)}>
          Gerar repasse
        </Button>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar repasses."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && settlements.length === 0 && (
        <SectionState
          title="Nenhum repasse gerado ainda."
          detail="Gere um repasse para consolidar os honorários de um prestador em uma competência."
        />
      )}

      {!loading && !error && settlements.length > 0 && (
        <SettlementList
          settlements={settlements}
          onApprove={(settlement) => setDeciding({ settlement, action: 'approve' })}
          onPay={(settlement) => setDeciding({ settlement, action: 'pay' })}
        />
      )}

      {deciding && (
        <SettlementDecideModal
          settlement={deciding.settlement}
          action={deciding.action}
          onClose={() => setDeciding(null)}
          onDone={applyUpdate}
        />
      )}

      {creating && (
        <SettlementCreateModal
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setSettlements((previous) => [created, ...previous])
            setCreating(false)
          }}
        />
      )}
    </PageShell>
  )
}
