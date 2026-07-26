import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import ContratosPage from './page'

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

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}))

// ─── Sample data ──────────────────────────────────────────────────────────────

const CONTRACT_ACTIVE = {
  id: 'c1',
  name: 'Comodato Hospital Central',
  client_name: 'Hospital Central',
  client: null,
  units: ['f1', 'f2'],
  monthly_value: '5000.00',
  start_date: '2026-01-01',
  end_date: '2026-12-31',
  status: 'ACTIVE',
}

const CONTRACT_EXPIRED = {
  id: 'c2',
  name: 'Comodato Clínica Sul',
  client_name: 'Clínica Sul',
  client: null,
  units: [],
  monthly_value: null,
  start_date: null,
  end_date: null,
  status: 'EXPIRED',
}

const FACILITIES = [
  { id: 'f1', name: 'Unidade Centro' },
  { id: 'f2', name: 'Unidade Norte' },
]

function mockList(contracts: any) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/concession-contracts/')) return Promise.resolve(contracts)
    if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
    if (path.startsWith('/api/v1/concession/services/')) return Promise.resolve([])
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('ContratosPage', () => {
  it('renders empty state when no contracts', async () => {
    mockList([])
    render(<ContratosPage />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhum contrato cadastrado/i)).toBeInTheDocument()
    })
  })

  it('renders contract rows when data loads', async () => {
    mockList([CONTRACT_ACTIVE, CONTRACT_EXPIRED])
    render(<ContratosPage />)

    await waitFor(() => {
      expect(screen.getByText('Comodato Hospital Central')).toBeInTheDocument()
    })

    const table = within(screen.getByRole('table'))
    expect(table.getByText('Hospital Central')).toBeInTheDocument()
    expect(table.getByText('Clínica Sul')).toBeInTheDocument()
    // units count for the active contract (2 units)
    expect(table.getByText('2')).toBeInTheDocument()
    // monthly value formatted as BRL
    expect(table.getByText(/5\.000,00/)).toBeInTheDocument()
    // status badge labels
    expect(table.getByText('Ativo')).toBeInTheDocument()
    expect(table.getByText('Expirado')).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))
    render(<ContratosPage />)

    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar contratos/i)).toBeInTheDocument()
    })
  })

  it('handles paginated {results,count} envelope', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.startsWith('/api/v1/concession-contracts/'))
        return Promise.resolve({ count: 1, results: [CONTRACT_ACTIVE] })
      if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
      if (path.startsWith('/api/v1/concession/services/')) return Promise.resolve([])
      return Promise.resolve([])
    })
    render(<ContratosPage />)

    await waitFor(() => {
      expect(screen.getByText('Comodato Hospital Central')).toBeInTheDocument()
    })
  })

  it('submits a create POST with the correct contract body', async () => {
    mockList([])
    render(<ContratosPage />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhum contrato cadastrado/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Novo contrato/i }))

    // wait for the modal facilities to load (units multiselect)
    await waitFor(() => {
      expect(screen.getByLabelText('Unidade Centro')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Nome do contrato/i), {
      target: { value: 'Comodato Hospital X' },
    })
    fireEvent.change(screen.getByLabelText(/Cliente/i), {
      target: { value: 'Hospital X' },
    })
    fireEvent.click(screen.getByLabelText('Unidade Centro'))
    fireEvent.change(screen.getByLabelText(/Valor mensal/i), {
      target: { value: '5000' },
    })
    fireEvent.change(screen.getByLabelText(/Início da vigência/i), {
      target: { value: '2026-01-01' },
    })
    fireEvent.change(screen.getByLabelText(/Fim da vigência/i), {
      target: { value: '2026-12-31' },
    })

    mockApiFetch.mockResolvedValueOnce({ ...CONTRACT_ACTIVE, id: 'c9' })

    fireEvent.click(screen.getByRole('button', { name: /Criar contrato/i }))

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url, init]) => url === '/api/v1/concession-contracts/' && init?.method === 'POST'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/concession-contracts/' && init?.method === 'POST'
    )
    const [, init] = call!
    expect(JSON.parse(init.body)).toEqual({
      name: 'Comodato Hospital X',
      client_name: 'Hospital X',
      client: null,
      units: ['f1'],
      monthly_value: '5000',
      start_date: '2026-01-01',
      end_date: '2026-12-31',
      status: 'ACTIVE',
    })
  })
})
