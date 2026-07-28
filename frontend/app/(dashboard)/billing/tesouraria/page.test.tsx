import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import TesourariaPage from './page'

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

const entry = (over: Record<string, any>) => ({
  id: 'cf',
  external_id: 'x',
  description: 'lanç',
  kind: 'inflow',
  amount: '0',
  due_date: '2026-08-01',
  realized_at: null,
  category: '',
  cost_center: '',
  status: 'forecast',
  created_at: '2026-07-01T10:00:00Z',
  ...over,
})

const ENTRIES = [
  entry({ id: 'cf-1', description: 'Recebimento Unimed', kind: 'inflow', amount: '1000.00', status: 'realized', due_date: '2026-08-03' }),
  entry({ id: 'cf-2', description: 'Pagamento aluguel', kind: 'outflow', amount: '400.00', status: 'realized', due_date: '2026-08-10' }),
  entry({ id: 'cf-3', description: 'Previsão consulta', kind: 'inflow', amount: '500.00', status: 'forecast', due_date: '2026-08-15' }),
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TesourariaPage', () => {
  it('renders empty state when no entries in period', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<TesourariaPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhum lançamento no período.')).toBeInTheDocument()
    })
  })

  it('renders summary totals and table when data loads', async () => {
    mockApiFetch.mockResolvedValueOnce(ENTRIES)
    render(<TesourariaPage />)
    // Summary always renders once loading finishes (regardless of period).
    await waitFor(() => {
      expect(screen.getByText('Entradas realizadas')).toBeInTheDocument()
    })
    // Align the period filter with the seeded 2026-08 entries.
    fireEvent.change(screen.getByLabelText('Período'), { target: { value: '2026-08' } })
    await waitFor(() => {
      expect(screen.getByText('Recebimento Unimed')).toBeInTheDocument()
    })

    // 1.000 / 400 appear in both the summary tile and the matching table row.
    expect(screen.getAllByText('R$ 1.000,00').length).toBeGreaterThan(0) // realized inflow
    expect(screen.getAllByText('R$ 400,00').length).toBeGreaterThan(0) // realized outflow
    expect(screen.getByText('R$ 600,00')).toBeInTheDocument() // saldo (summary only)
    expect(screen.getByText('Pagamento aluguel')).toBeInTheDocument()
    expect(screen.getByText('Previsão consulta')).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<TesourariaPage />)
    await waitFor(() => {
      expect(screen.getByText('Fluxo de caixa indisponível')).toBeInTheDocument()
    })
  })

  it('reloads with kind filter as a query param', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<TesourariaPage />)
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    mockApiFetch.mockResolvedValueOnce([])
    fireEvent.change(screen.getByLabelText('Tipo'), { target: { value: 'inflow' } })

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(([url]) => String(url).includes('kind=inflow'))
      expect(call).toBeTruthy()
    })
  })
})
