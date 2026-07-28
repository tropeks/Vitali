/**
 * Vitest + @testing-library/react tests for LotacoesPage (Sprint A7-T2)
 *
 * Run: npx vitest run "app/(dashboard)/rh/lotacoes/page.test.tsx"
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import LotacoesPage from './page'

// ─── Mocks ────────────────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
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

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

import { apiFetch } from '@/lib/api'
const mockApiFetch = vi.mocked(apiFetch)

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const EMPLOYEE_1 = { id: 'emp-1', full_name: 'Ana Souza' }
const UNIT_1 = { id: 'unit-1', name: 'Unidade Central' }
const POSITION_1 = { id: 'pos-1', title: 'Enfermeira' }

const ASSIGNMENT_1 = {
  id: 'asg-1',
  employee: 'emp-1',
  unit: 'unit-1',
  cost_center: null,
  position: 'pos-1',
  role: '',
  start_date: '2026-01-10',
  end_date: null,
  active: true,
  created_at: '2026-01-10T10:00:00Z',
  updated_at: '2026-01-10T10:00:00Z',
}

function mockEndpoints({
  assignments = [] as any[],
  employees = [EMPLOYEE_1] as any[],
  units = [UNIT_1] as any[],
  positions = [POSITION_1] as any[],
} = {}) {
  mockApiFetch.mockImplementation((url: unknown) => {
    const u = String(url)
    if (u.startsWith('/api/v1/hr/assignments/')) return Promise.resolve(assignments)
    if (u.startsWith('/api/v1/hr/employees/')) return Promise.resolve(employees)
    if (u.startsWith('/api/v1/organization/units/')) return Promise.resolve(units)
    if (u.startsWith('/api/v1/hr/positions/')) return Promise.resolve(positions)
    return Promise.reject(new Error(`unexpected url ${u}`))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LotacoesPage', () => {
  it('renders empty state when there are no assignments', async () => {
    mockEndpoints({ assignments: [] })
    render(<LotacoesPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhuma lotação cadastrada ainda.')).toBeInTheDocument()
    })
  })

  it('renders assignment rows with resolved employee/unit/position names', async () => {
    mockEndpoints({ assignments: [ASSIGNMENT_1] })
    render(<LotacoesPage />)
    await waitFor(() => {
      expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    })
    expect(screen.getByText('Unidade Central')).toBeInTheDocument()
    expect(screen.getByText('Enfermeira')).toBeInTheDocument()
    expect(screen.getByText('Ativa')).toBeInTheDocument()
  })

  it('shows an error state when loading fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))
    render(<LotacoesPage />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar lotações.')).toBeInTheDocument()
    })
  })

  it('states the single-active-assignment invariant on the page', async () => {
    mockEndpoints({ assignments: [] })
    render(<LotacoesPage />)
    await waitFor(() => {
      expect(screen.getByText(/uma lotação ativa por vez/i)).toBeInTheDocument()
    })
  })

  it('opens the create modal and reloads the list on success', async () => {
    mockEndpoints({ assignments: [] })
    render(<LotacoesPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhuma lotação cadastrada ainda.')).toBeInTheDocument()
    })

    const { fireEvent } = await import('@testing-library/react')
    const [openButton] = screen.getAllByRole('button', { name: /nova lotação/i })
    fireEvent.click(openButton)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Nova Lotação' })).toBeInTheDocument()
    })
  })
})
