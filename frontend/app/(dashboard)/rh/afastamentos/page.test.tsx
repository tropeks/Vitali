import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AfastamentosPage from './page'

// ─── Mocks ────────────────────────────────────────────────────────────────────

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
  ApiError: class ApiError extends Error {
    status: number
    body: any
    constructor(status: number, body: any, message?: string) {
      super(message ?? `API error ${status}`)
      this.status = status
      this.body = body
    }
  },
}))

// ─── Sample data ──────────────────────────────────────────────────────────────

const ME = { id: 'user-1' }
const EMPLOYEES = [
  { id: 'emp-1', full_name: 'Ana Souza' },
  { id: 'emp-2', full_name: 'Bruno Lima' },
]

const REQ_OWN = {
  id: 'lr-1',
  employee: 'emp-1',
  employee_name: 'Ana Souza',
  leave_type: 'ferias',
  leave_type_display: 'Férias',
  start_date: '2026-08-01',
  end_date: '2026-08-10',
  reason: 'Descanso anual',
  status: 'pending' as const,
  approval: null,
  requested_by: 'user-1', // same as ME → own request
  requested_by_name: 'Ana (RH)',
  created_at: '2026-07-20T10:00:00Z',
  updated_at: '2026-07-20T10:00:00Z',
}

const REQ_OTHER = {
  ...REQ_OWN,
  id: 'lr-2',
  employee: 'emp-2',
  employee_name: 'Bruno Lima',
  reason: 'Viagem',
  requested_by: 'user-2', // different user → decidable
  requested_by_name: 'Bruno (RH)',
}

// path-based routing so call order / count doesn't matter
function routeMock(opts: { me?: any; list?: any[]; emp?: any[]; listError?: boolean } = {}) {
  const { me = ME, list = [], emp = EMPLOYEES, listError = false } = opts
  mockApiFetch.mockImplementation((path: string) => {
    if (path === '/api/v1/me') return Promise.resolve(me)
    if (path === '/api/v1/hr/leave-requests/')
      return listError ? Promise.reject(new Error('boom')) : Promise.resolve(list)
    if (path === '/api/v1/hr/employees/') return Promise.resolve(emp)
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('AfastamentosPage', () => {
  it('renders empty state when there are no requests', async () => {
    routeMock({ list: [] })

    render(<AfastamentosPage />)

    await waitFor(() => {
      expect(
        screen.getByText('Nenhuma solicitação de afastamento ainda.')
      ).toBeInTheDocument()
    })
  })

  it('renders request rows when data loads', async () => {
    routeMock({ list: [REQ_OWN, REQ_OTHER] })

    render(<AfastamentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    })
    expect(screen.getByText('Bruno Lima')).toBeInTheDocument()
    expect(screen.getAllByText('Pendente').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Férias').length).toBeGreaterThan(0)
  })

  it('shows error state when the list fetch fails', async () => {
    routeMock({ listError: true })

    render(<AfastamentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar afastamentos.')).toBeInTheDocument()
    })
  })

  it('maker-checker: shows a decide action for others but not for own request', async () => {
    routeMock({ list: [REQ_OWN, REQ_OTHER] })

    render(<AfastamentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Bruno Lima')).toBeInTheDocument()
    })

    // Only REQ_OTHER (requested_by user-2) is decidable by ME (user-1).
    const decideButtons = screen.getAllByRole('button', { name: /Decidir/ })
    expect(decideButtons).toHaveLength(1)
  })
})
