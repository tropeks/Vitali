import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ContractDetailPage from './page'

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

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'c1' }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}))

// ─── Sample data ──────────────────────────────────────────────────────────────

const CONTRACT = {
  id: 'c1',
  name: 'Comodato Hospital Central',
  client_name: 'Hospital Central',
  client: null,
  units: ['f1'],
  monthly_value: '5000.00',
  start_date: '2026-01-01',
  end_date: '2026-12-31',
  status: 'ACTIVE',
}

const SERVICES = [
  { id: 's1', code: 'US', name: 'Ultrassom', modality: 'US', tuss_code: '40901112', active: true },
  { id: 's2', code: 'RX', name: 'Raio-X', modality: 'RX', tuss_code: '40801012', active: true },
]

const FACILITIES = [
  { id: 'f1', name: 'Unidade Centro' },
  { id: 'f2', name: 'Unidade Norte' },
]

const MATERIALS = [
  { id: 'm1', name: 'Gel para ultrassom', unit_of_measure: 'ml' },
  { id: 'm2', name: 'Filme radiográfico', unit_of_measure: 'un' },
]

function baseMock({ prices = [] as any[], recipes = [] as any[] } = {}) {
  mockApiFetch.mockImplementation((path: string, init?: any) => {
    const method = init?.method
    if (path === '/api/v1/concession-contracts/c1/') return Promise.resolve(CONTRACT)
    if (path.startsWith('/api/v1/concession/services/')) return Promise.resolve(SERVICES)
    if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
    if (path.startsWith('/api/v1/pharmacy/materials/')) return Promise.resolve(MATERIALS)
    if (path.startsWith('/api/v1/service-recipes/')) {
      if (!method || method === 'GET') return Promise.resolve(recipes)
      return Promise.resolve({})
    }
    if (path.startsWith('/api/v1/contract-prices/')) {
      if (!method || method === 'GET') return Promise.resolve(prices)
      return Promise.resolve({})
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('ContractDetailPage', () => {
  it('renders the contract header and price matrix rows', async () => {
    baseMock()
    render(<ContractDetailPage />)

    await waitFor(() => {
      expect(screen.getByText('Comodato Hospital Central')).toBeInTheDocument()
    })
    // one price input per service (contract-scoped) — the matrix loads its
    // own prices async, so wait for the first row to appear.
    await waitFor(() => {
      expect(screen.getByLabelText('Preço US')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Preço RX')).toBeInTheDocument()
  })

  it('POSTs a contract-scoped price with the correct body', async () => {
    baseMock()
    render(<ContractDetailPage />)

    await waitFor(() => {
      expect(screen.getByLabelText('Preço US')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText('Preço US'), { target: { value: '150.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar US' }))

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url, init]) => url === '/api/v1/contract-prices/' && init?.method === 'POST'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/contract-prices/' && init?.method === 'POST'
    )
    const [, init] = call!
    expect(JSON.parse(init.body)).toEqual({
      contract: 'c1',
      unit: null,
      service: 's1',
      price: '150.00',
      is_billable: true,
    })
  })

  it('PUTs an existing contract-scoped price when it already has an id', async () => {
    baseMock({
      prices: [
        {
          id: 'p1',
          contract: 'c1',
          unit: null,
          service: 's1',
          price: '150.00',
          is_billable: true,
        },
      ],
    })
    render(<ContractDetailPage />)

    await waitFor(() => {
      expect(screen.getByLabelText('Preço US')).toHaveValue('150.00')
    })

    fireEvent.change(screen.getByLabelText('Preço US'), { target: { value: '200.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar US' }))

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url, init]) => url === '/api/v1/contract-prices/p1/' && init?.method === 'PUT'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/contract-prices/p1/' && init?.method === 'PUT'
    )
    const [, init] = call!
    expect(JSON.parse(init.body)).toEqual({
      contract: 'c1',
      unit: null,
      service: 's1',
      price: '200.00',
      is_billable: true,
    })
  })

  it('POSTs a unit-override price with the correct body', async () => {
    baseMock()
    render(<ContractDetailPage />)

    await waitFor(() => {
      expect(screen.getByLabelText('Preço US')).toBeInTheDocument()
    })

    // reveal the unit-override draft row for service US
    fireEvent.click(screen.getByRole('button', { name: /Adicionar override US/i }))

    fireEvent.change(screen.getByLabelText('Unidade do override US'), {
      target: { value: 'f1' },
    })
    fireEvent.change(screen.getByLabelText('Preço override US'), {
      target: { value: '120.00' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar override US' }))

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url, init]) => url === '/api/v1/contract-prices/' && init?.method === 'POST'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/contract-prices/' && init?.method === 'POST'
    )
    const [, init] = call!
    expect(JSON.parse(init.body)).toEqual({
      contract: 'c1',
      unit: 'f1',
      service: 's1',
      price: '120.00',
      is_billable: true,
    })
  })

  it('POSTs a recipe line with the correct body', async () => {
    baseMock()
    render(<ContractDetailPage />)

    await waitFor(() => {
      expect(screen.getByLabelText('Serviço da receita')).toBeInTheDocument()
    })

    // default selected service is the first one (s1). Pick a material + quantity.
    fireEvent.change(screen.getByLabelText('Insumo da receita'), {
      target: { value: 'm1' },
    })
    fireEvent.change(screen.getByLabelText('Quantidade por exame'), {
      target: { value: '2' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Adicionar insumo/i }))

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url, init]) => url === '/api/v1/service-recipes/' && init?.method === 'POST'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/service-recipes/' && init?.method === 'POST'
    )
    const [, init] = call!
    expect(JSON.parse(init.body)).toEqual({
      service: 's1',
      material: 'm1',
      quantity: '2',
    })
  })
})
