import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import SurgeryCasePanel from './SurgeryCasePanel'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

const CASE = {
  id: 'case-1',
  patient: 'patient-1',
  surgeon: 'prof-1',
  operating_room: 'room-1',
  scheduled_start: '2026-07-25T13:00:00Z',
  priority: 'urgencia',
  status: 'agendada',
}

const ROOMS = [{ id: 'room-1', code: 'S1', name: 'Sala 1' }]

const PROCEDURES = [
  { id: 'proc-1', case: 'case-1', tuss_code_value: '31003010', quantity: 1 },
]

const TIMELINE = {
  case: 'case-1',
  status: 'agendada',
  times: [],
  checklists: [],
  team: [],
}

/** Route apiFetch by URL across every endpoint the panel + intra-op touch. */
function routeApi(overrides: { cases?: any } = {}) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/surgical-cases/?patient=')) {
      return Promise.resolve(overrides.cases ?? [CASE])
    }
    if (url === '/api/v1/operating-rooms/') return Promise.resolve(ROOMS)
    if (url.startsWith('/api/v1/surgical-procedures/?case=')) {
      return Promise.resolve(PROCEDURES)
    }
    if (url.includes('/timeline/')) return Promise.resolve(TIMELINE)
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SurgeryCasePanel', () => {
  it('hides everything without surgery.read', () => {
    routeApi()
    render(<SurgeryCasePanel patientId="patient-1" canRead={false} canManage />)
    expect(screen.getByText('Sem acesso ao centro cirúrgico')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('fetches the patient surgical cases with surgery.read', async () => {
    routeApi()
    render(<SurgeryCasePanel patientId="patient-1" canRead canManage={false} />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/surgical-cases/?patient=patient-1',
      )
    })
  })

  it('lists cases with status, priority, room and procedures', async () => {
    routeApi()
    render(<SurgeryCasePanel patientId="patient-1" canRead canManage />)
    await waitFor(() => {
      expect(screen.getByText('Agendada')).toBeInTheDocument()
    })
    // Priority label from the enum map.
    expect(screen.getByText('Urgência')).toBeInTheDocument()
    // Room resolved from /operating-rooms/ (code — name).
    expect(screen.getByText('S1 — Sala 1')).toBeInTheDocument()
    // Procedure summary (tuss_code_value).
    expect(screen.getByText(/31003010/)).toBeInTheDocument()
  })

  it('shows an empty state with no cases', async () => {
    routeApi({ cases: [] })
    render(<SurgeryCasePanel patientId="patient-1" canRead canManage />)
    await waitFor(() => {
      expect(screen.getByText('Sem cirurgia registrada')).toBeInTheDocument()
    })
  })

  it('opens the intra-op panel (timeline) when a case is selected', async () => {
    routeApi()
    render(<SurgeryCasePanel patientId="patient-1" canRead canManage />)
    await waitFor(() => {
      expect(screen.getByText('S1 — Sala 1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /S1 — Sala 1/ }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/surgical-cases/case-1/timeline/')
    })
    expect(screen.getByText('Tempos cirúrgicos')).toBeInTheDocument()
  })
})
