'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import ContractList from '@/components/concession/ContractList'
import ContractFormModal from '@/components/concession/ContractFormModal'
import ServiceCatalogManager from '@/components/concession/ServiceCatalogManager'
import { unwrap, type ConcessionContract, type Listish } from '@/components/concession/contractMeta'

export default function ContratosPage() {
  const [contracts, setContracts] = useState<ConcessionContract[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ConcessionContract | null>(null)

  const loadContracts = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<Listish<ConcessionContract>>('/api/v1/concession-contracts/')
      setContracts(unwrap(data))
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadContracts()
  }, [loadContracts])

  function openCreate() {
    setEditing(null)
    setFormOpen(true)
  }

  function openEdit(contract: ConcessionContract) {
    setEditing(contract)
    setFormOpen(true)
  }

  return (
    <PageShell variant="operational">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Contratos de concessão</h1>
          <p className="mt-0.5 text-sm text-neu-inkMuted">
            Comodatos por cliente, unidades atendidas e valor mensal do contrato.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="rounded-lg bg-neu-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          + Novo contrato
        </button>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar contratos."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && contracts.length === 0 && (
        <SectionState
          title="Nenhum contrato cadastrado ainda."
          detail='Clique em "+ Novo contrato" para registrar o primeiro comodato.'
        />
      )}

      {!loading && !error && contracts.length > 0 && (
        <ContractList contracts={contracts} onEdit={openEdit} />
      )}

      <ServiceCatalogManager />

      <ContractFormModal
        open={formOpen}
        contract={editing}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          loadContracts()
        }}
      />
    </PageShell>
  )
}
