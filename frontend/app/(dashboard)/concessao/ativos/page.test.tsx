import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import AtivosPage from './page'

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

const ASSET_ACTIVE = {
  id: 'a1',
  asset_tag: 'PAT-001',
  name: 'Ultrassom Sala 1',
  model: 'GE Vivid E95',
  serial_number: 'SN-1',
  status: 'ACTIVE',
  ownership: 'OPERATOR',
  purchase_cost: '120000.00',
  useful_life_months: 60,
  purchase_date: '2024-01-01',
  current_location: 'f1',
  active: true,
  monthly_depreciation: '2000.00',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

const ASSET_MAINT = {
  id: 'a2',
  asset_tag: 'PAT-002',
  name: 'Tomógrafo',
  model: 'Siemens Somatom',
  serial_number: 'SN-2',
  status: 'IN_MAINTENANCE',
  ownership: 'CLIENT',
  purchase_cost: null,
  useful_life_months: null,
  purchase_date: null,
  current_location: null,
  active: true,
  monthly_depreciation: '0.00',
  created_at: '2024-02-01T00:00:00Z',
  updated_at: '2024-02-01T00:00:00Z',
}

const FACILITIES = [{ id: 'f1', name: 'Unidade Centro' }]

function mockList(assets: any) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/concession/assets/')) return Promise.resolve(assets)
    if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('AtivosPage', () => {
  it('renders empty state when no assets', async () => {
    mockList([])
    render(<AtivosPage />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhum ativo cadastrado/i)).toBeInTheDocument()
    })
  })

  it('renders asset rows when data loads', async () => {
    mockList([ASSET_ACTIVE, ASSET_MAINT])
    render(<AtivosPage />)

    await waitFor(() => {
      expect(screen.getByText('PAT-001')).toBeInTheDocument()
    })

    // Assertions scoped to the table — the filter selects reuse the same
    // status/ownership labels as <option> text.
    const table = within(screen.getByRole('table'))
    // tag / name / model
    expect(table.getByText('Ultrassom Sala 1')).toBeInTheDocument()
    expect(table.getByText('GE Vivid E95')).toBeInTheDocument()
    // status badge label
    expect(table.getByText('Ativo')).toBeInTheDocument()
    expect(table.getByText('Em manutenção')).toBeInTheDocument()
    // ownership label
    expect(table.getByText('Operadora')).toBeInTheDocument()
    expect(table.getByText('Cliente')).toBeInTheDocument()
    // location resolved from facilities map, null → warehouse
    expect(table.getByText('Unidade Centro')).toBeInTheDocument()
    expect(table.getByText('Armazém')).toBeInTheDocument()
    // depreciation formatted as BRL currency
    expect(table.getByText(/2\.000,00/)).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))
    render(<AtivosPage />)

    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar ativos/i)).toBeInTheDocument()
    })
  })

  it('handles paginated {results,count} envelope', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.startsWith('/api/v1/concession/assets/'))
        return Promise.resolve({ count: 1, results: [ASSET_ACTIVE] })
      if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
      return Promise.resolve([])
    })
    render(<AtivosPage />)

    await waitFor(() => {
      expect(screen.getByText('PAT-001')).toBeInTheDocument()
    })
  })

  it('filters the table by status', async () => {
    mockList([ASSET_ACTIVE, ASSET_MAINT])
    render(<AtivosPage />)

    await waitFor(() => {
      expect(screen.getByText('PAT-001')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Filtrar por status/i), {
      target: { value: 'IN_MAINTENANCE' },
    })

    expect(screen.queryByText('PAT-001')).not.toBeInTheDocument()
    expect(screen.getByText('PAT-002')).toBeInTheDocument()
  })

  it('opens the create form when clicking + Novo ativo', async () => {
    mockList([ASSET_ACTIVE])
    render(<AtivosPage />)

    await waitFor(() => {
      expect(screen.getByText('PAT-001')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Novo ativo/i }))

    expect(screen.getByRole('button', { name: /Criar ativo/i })).toBeInTheDocument()
  })
})
