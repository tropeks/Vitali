'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import PositionList from '@/components/hr/PositionList'
import PositionFormModal from '@/components/hr/PositionFormModal'

export interface Position {
  id: string
  title: string
  cbo: string
  active: boolean
  created_at: string
  updated_at: string
}

const PRIMARY_BTN =
  'px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all'

export default function CargosPage() {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editingPosition, setEditingPosition] = useState<Position | null>(null)

  const loadPositions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<Position[] | { results: Position[] }>(
        '/api/v1/hr/positions/'
      )
      setPositions(Array.isArray(data) ? data : (data as { results: Position[] }).results ?? [])
    } catch {
      setError('Erro ao carregar cargos.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPositions()
  }, [loadPositions])

  function openCreate() {
    setEditingPosition(null)
    setFormOpen(true)
  }

  function openEdit(position: Position) {
    setEditingPosition(position)
    setFormOpen(true)
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Cargos</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Cargos disponíveis para lotação de funcionários.
          </p>
        </div>
        <button onClick={openCreate} className={PRIMARY_BTN}>
          + Novo Cargo
        </button>
      </div>

      {error && (
        <SectionState
          title="Erro ao carregar cargos."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && positions.length === 0 && (
        <SectionState
          title="Nenhum cargo cadastrado ainda."
          detail="Cadastre o primeiro cargo para usá-lo na lotação de funcionários."
          action={
            <button onClick={openCreate} className={PRIMARY_BTN}>
              + Novo Cargo
            </button>
          }
        />
      )}

      {!loading && !error && positions.length > 0 && (
        <PositionList positions={positions} onEdit={openEdit} />
      )}

      <PositionFormModal
        open={formOpen}
        position={editingPosition}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          loadPositions()
        }}
      />
    </PageShell>
  )
}
