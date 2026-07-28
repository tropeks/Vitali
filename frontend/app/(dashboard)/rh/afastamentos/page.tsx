'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'
import { PageShell, SectionState } from '@/components/shared'
import LeaveRequestList from '@/components/hr/LeaveRequestList'
import LeaveRequestForm from '@/components/hr/LeaveRequestForm'
import LeaveDecideModal from '@/components/hr/LeaveDecideModal'

export interface LeaveApproval {
  decided_by?: string
  decided_by_name?: string
  decision?: string
  notes?: string
  decided_at?: string
}

export interface LeaveRequest {
  id: string
  employee: string
  employee_name?: string
  leave_type: string
  leave_type_display?: string
  start_date: string
  end_date: string
  reason: string
  // server-set / read-only
  status: 'pending' | 'approved' | 'rejected'
  status_display?: string
  approval?: LeaveApproval | null
  requested_by: string
  requested_by_name?: string
  created_at: string
  updated_at: string
}

interface EmployeeOption {
  id: string
  full_name: string
}

interface Me {
  id: string
}

export default function AfastamentosPage() {
  const [requests, setRequests] = useState<LeaveRequest[]>([])
  const [employees, setEmployees] = useState<EmployeeOption[]>([])
  const [currentUserId, setCurrentUserId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [decidingRequest, setDecidingRequest] = useState<LeaveRequest | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // /me and /employees are auxiliary: a failure there must not block the list.
      const [me, list, emps] = await Promise.all([
        apiFetch<Me>('/api/v1/me').catch(() => null),
        apiFetch<LeaveRequest[] | { results: LeaveRequest[] }>('/api/v1/hr/leave-requests/'),
        apiFetch<EmployeeOption[] | { results: EmployeeOption[] }>(
          '/api/v1/hr/employees/'
        ).catch(() => [] as EmployeeOption[]),
      ])
      setCurrentUserId(me?.id ?? null)
      setRequests(Array.isArray(list) ? list : (list as { results: LeaveRequest[] }).results ?? [])
      setEmployees(Array.isArray(emps) ? emps : (emps as { results: EmployeeOption[] }).results ?? [])
    } catch {
      setError('Erro ao carregar afastamentos.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function flashSuccess(msg: string) {
    setSuccessMessage(msg)
    setTimeout(() => setSuccessMessage(null), 4000)
  }

  return (
    <PageShell variant="operational">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-neu-ink">Afastamentos</h1>
          <p className="text-sm text-neu-inkMuted mt-0.5">
            Férias e licenças da equipe. A aprovação segue maker-checker: quem solicita não decide.
          </p>
        </div>
        <button
          onClick={() => setFormOpen(true)}
          className="px-4 py-2 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white text-sm font-medium rounded-lg hover:shadow-neu-btn-primary-hover transition-all"
        >
          + Solicitar afastamento
        </button>
      </div>

      {successMessage && (
        <SectionState title={successMessage} detail="Operação concluída." tone="success" />
      )}

      {error && (
        <SectionState
          title="Erro ao carregar afastamentos."
          detail="Verifique sua conexão e tente novamente."
          tone="critical"
        />
      )}

      {loading && <p className="text-sm text-neu-inkMuted">Carregando...</p>}

      {!loading && !error && (
        <LeaveRequestList
          requests={requests}
          currentUserId={currentUserId}
          onDecide={(req) => setDecidingRequest(req)}
        />
      )}

      <LeaveRequestForm
        open={formOpen}
        employees={employees}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false)
          flashSuccess('Solicitação de afastamento enviada ✓')
          load()
        }}
      />

      <LeaveDecideModal
        open={decidingRequest !== null}
        request={decidingRequest}
        onClose={() => setDecidingRequest(null)}
        onDecided={() => {
          setDecidingRequest(null)
          flashSuccess('Decisão registrada ✓')
          load()
        }}
      />
    </PageShell>
  )
}
