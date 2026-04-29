'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import ProfessionalRow from '@/components/professionals/ProfessionalRow'
import type { Professional } from '@/components/professionals/ProfessionalRow'

// ─── Component ────────────────────────────────────────────────────────────────

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
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Profissionais</h1>
        <p className="text-sm text-slate-500 mt-0.5">Equipe clínica cadastrada na clínica.</p>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <p className="text-sm text-slate-500">Carregando...</p>
      )}

      {/* Empty state */}
      {!loading && !error && professionals.length === 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm py-16 flex flex-col items-center gap-3">
          <p className="text-slate-500 text-sm">Nenhum profissional cadastrado ainda.</p>
          <p className="text-slate-400 text-xs text-center max-w-sm">
            Profissionais são criados automaticamente quando você adiciona um funcionário com função
            clínica em /rh/funcionarios.
          </p>
        </div>
      )}

      {/* Table */}
      {!loading && !error && professionals.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Nome', 'Email', 'Conselho', 'Especialidade', 'Status'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 font-medium text-slate-600">
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
    </div>
  )
}
