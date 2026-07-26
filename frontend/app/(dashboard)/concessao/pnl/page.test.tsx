import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PnlPage from './page'

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

// The cost-breakdown chart uses recharts (ResponsiveContainer renders nothing
// at 0px in jsdom). Stub it so the page test asserts data, not SVG geometry.
vi.mock('@/components/concession/PnlCostBreakdownChart', () => ({
  default: ({ breakdown }: any) => (
    <div data-testid="cost-chart">chart:{breakdown.consumption}</div>
  ),
}))

const CONTRACTS = [
  {
    id: 'c1',
    name: 'Contrato Alfa',
    client_name: 'Hospital X',
    client: null,
    units: ['f1'],
    monthly_value: '10000.00',
    start_date: null,
    end_date: null,
    status: 'ACTIVE',
  },
]
const FACILITIES = [{ id: 'f1', name: 'Unidade Centro' }]
const PNL = {
  contract: 1,
  units: ['f1'],
  start: '2026-07-01',
  end: '2026-07-31',
  exam_volume: 120,
  revenue: 48000,
  cost: 18000,
  result: 30000,
  cost_breakdown: { consumption: 15000, freight: 0, maintenance: 3000 },
  by_service: [
    {
      service: 10,
      service_code: 'RM01',
      service_name: 'Ressonância Magnética',
      exam_volume: 80,
      revenue: 40000,
      consumption_cost: 12000,
    },
  ],
}

function routeReads(pnl: any = PNL) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.includes('/pnl/')) {
      if (pnl instanceof Error) return Promise.reject(pnl)
      return Promise.resolve(pnl)
    }
    if (path.startsWith('/api/v1/concession-contracts/')) return Promise.resolve(CONTRACTS)
    if (path.startsWith('/api/v1/organization/facilities/')) return Promise.resolve(FACILITIES)
    return Promise.resolve({ results: [] })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PnlPage', () => {
  it('prompts to select a contract before any P&L is computed', async () => {
    routeReads()
    render(<PnlPage />)

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Contrato Alfa/ })).toBeInTheDocument()
    })
    expect(screen.getByText(/Selecione um contrato/i)).toBeInTheDocument()
  })

  it('renders KPI tiles, cost breakdown and per-service table from the P&L response', async () => {
    routeReads()
    render(<PnlPage />)

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Contrato Alfa/ })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Contrato/i), { target: { value: 'c1' } })

    // KPI values (receita / custo / resultado / volume).
    await waitFor(() => {
      expect(screen.getByText('R$ 48.000,00')).toBeInTheDocument()
    })
    expect(screen.getByText('R$ 18.000,00')).toBeInTheDocument()
    expect(screen.getByText('R$ 30.000,00')).toBeInTheDocument()
    expect(screen.getByText('120')).toBeInTheDocument()

    // Cost breakdown chart received the data.
    expect(screen.getByTestId('cost-chart')).toHaveTextContent('chart:15000')

    // Per-service profitability row.
    expect(screen.getByText('Ressonância Magnética')).toBeInTheDocument()
    expect(screen.getByText('RM01')).toBeInTheDocument()
    expect(screen.getByText('R$ 40.000,00')).toBeInTheDocument()

    // The P&L request carried the selected contract id + a period.
    const pnlCall = mockApiFetch.mock.calls.find((c) => String(c[0]).includes('/pnl/'))
    expect(pnlCall).toBeTruthy()
    expect(String(pnlCall![0])).toContain('/api/v1/concession/contracts/c1/pnl/')
    expect(String(pnlCall![0])).toMatch(/start=\d{4}-\d{2}-\d{2}/)
    expect(String(pnlCall![0])).toMatch(/end=\d{4}-\d{2}-\d{2}/)
  })

  it('shows an error state when the P&L request fails', async () => {
    routeReads(new Error('pnl down'))
    render(<PnlPage />)

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Contrato Alfa/ })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Contrato/i), { target: { value: 'c1' } })

    await waitFor(() => {
      expect(screen.getByText(/Erro ao calcular o P&L/i)).toBeInTheDocument()
    })
  })
})
