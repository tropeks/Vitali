'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import ProfessionalRow from '@/components/professionals/ProfessionalRow'
import type { Professional } from '@/components/professionals/ProfessionalRow'

export default function ProfissionaisPage() {
  const [professionals, setProfessionals] = useState<Professional[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadProfessionals = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<Professional[] | { results: Professional[] }>(
        '/api/v1/professionals/'
      )
      setProfessionals(
        Array.isArray(data) ? data : (data as { results: Professional[] }).results ?? []
      )
    } catch {
      setError('Erro ao carregar profissionais.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProfessionals()
  }, [loadProfessionals])

  return (
    <PageShell variant="operational">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Profissionais</h1>
        <p className="text-sm text-slate-500 mt-0.5">Equipe clínica cadastrada na clínica.</p>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar profissionais."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-slate-500">Carregando...</p>}

      {!loading && !error && professionals.length === 0 && (
        <SectionState
          title="Nenhum profissional cadastrado ainda."
          detail="Profissionais são criados automaticamente quando você adiciona um funcionário com função clínica em /rh/funcionarios."
        />
      )}

      {!loading && !error && professionals.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Nome', 'Email', 'Conselho', 'Especialidade', 'Status'].map((h) => (
                  <th
                    key={h}
                    className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {professionals.map((pro) => (
                <ProfessionalRow key={pro.id} professional={pro} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  )
}
