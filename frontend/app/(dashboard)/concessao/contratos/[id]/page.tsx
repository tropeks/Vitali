'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState, StatusBadge } from '@/components/shared'
import PriceMatrix from '@/components/concession/PriceMatrix'
import RecipeEditor from '@/components/concession/RecipeEditor'
import {
  contractStatusMeta,
  formatBRL,
  formatDate,
  unwrap,
  type ConcessionContract,
  type ConcessionService,
  type FacilityOption,
  type Listish,
  type MaterialOption,
} from '@/components/concession/contractMeta'

export default function ContractDetailPage() {
  const params = useParams()
  const id = params.id as string

  const [contract, setContract] = useState<ConcessionContract | null>(null)
  const [services, setServices] = useState<ConcessionService[]>([])
  const [facilities, setFacilities] = useState<FacilityOption[]>([])
  const [materials, setMaterials] = useState<MaterialOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [recipeService, setRecipeService] = useState('')

  const loadContract = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await apiFetch<ConcessionContract>(`/api/v1/concession-contracts/${id}/`)
      setContract(data)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [id])

  const loadCatalog = useCallback(async () => {
    try {
      const [svc, fac, mat] = await Promise.all([
        apiFetch<Listish<ConcessionService>>('/api/v1/concession/services/'),
        apiFetch<Listish<FacilityOption>>('/api/v1/organization/facilities/'),
        apiFetch<Listish<MaterialOption>>('/api/v1/pharmacy/materials/'),
      ])
      const svcList = unwrap(svc)
      setServices(svcList)
      setFacilities(unwrap(fac))
      setMaterials(unwrap(mat))
      setRecipeService((prev) => prev || svcList[0]?.id || '')
    } catch {
      setServices([])
      setFacilities([])
      setMaterials([])
    }
  }, [])

  useEffect(() => {
    loadContract()
    loadCatalog()
  }, [loadContract, loadCatalog])

  const selectedService = useMemo(
    () => services.find((s) => s.id === recipeService) ?? null,
    [services, recipeService]
  )

  return (
    <PageShell variant="operational">
      <Link
        href="/concessao/contratos"
        className="inline-flex items-center gap-1 text-sm text-neu-inkMuted hover:text-neu-ink"
      >
        <ArrowLeft size={16} /> Voltar aos contratos
      </Link>

      {error && (
        <SectionState
          title="Erro ao carregar o contrato."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && !contract && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {contract && (
        <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-semibold text-neu-ink">{contract.name}</h1>
                <StatusBadge meta={contractStatusMeta(contract.status)} />
              </div>
              <p className="mt-0.5 text-sm text-neu-inkMuted">
                {contract.client_name || 'Sem cliente'} · {formatBRL(contract.monthly_value)}/mês ·
                Vigência {formatDate(contract.start_date)} – {formatDate(contract.end_date)}
              </p>
            </div>
          </div>

          <PriceMatrix contractId={contract.id} services={services} facilities={facilities} />

          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Receitas (insumo por exame)</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Materiais consumidos por exame de cada serviço concessionado.
            </p>

            {services.length === 0 ? (
              <p className="mt-3 text-sm text-neu-inkMuted">
                Cadastre serviços no catálogo para montar receitas.
              </p>
            ) : (
              <div className="mt-3">
                <label htmlFor="recipe-service" className="mb-1 block text-xs font-medium text-slate-700">
                  Serviço
                </label>
                <select
                  id="recipe-service"
                  aria-label="Serviço da receita"
                  className="border border-slate-200 rounded-lg px-2 py-1 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={recipeService}
                  onChange={(e) => setRecipeService(e.target.value)}
                >
                  {services.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.code} — {s.name}
                    </option>
                  ))}
                </select>

                {selectedService && (
                  <RecipeEditor
                    key={selectedService.id}
                    serviceId={selectedService.id}
                    materials={materials}
                  />
                )}
              </div>
            )}
          </section>
        </>
      )}
    </PageShell>
  )
}
