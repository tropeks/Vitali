import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ConsumptionLedger from './ConsumptionLedger'

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

const FACILITIES = [{ id: 'f1', name: 'Unidade Centro' }]
const SERVICES = [{ id: 10, code: 'RM01', name: 'Ressonância Magnética' }]
const CONSUMPTIONS = [
  {
    id: 1,
    unit: 'f1',
    service: 10,
    external_ref: 'EXT-1',
    dicom_study: null,
    source_warehouse: null,
    performed_at: '2026-07-20T14:30:00Z',
    cost_snapshot: '45.00',
    idempotency_key: 'k1',
    created_at: '2026-07-20T14:30:05Z',
  },
]

function routeReads(consumptions = CONSUMPTIONS) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/concession/exam-consumptions/'))
      return Promise.resolve({ count: consumptions.length, results: consumptions })
    if (path.startsWith('/api/v1/organization/facilities/')) return Promise.resolve(FACILITIES)
    if (path.startsWith('/api/v1/concession/services/'))
      return Promise.resolve({ count: SERVICES.length, results: SERVICES })
    return Promise.resolve({ results: [] })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ConsumptionLedger', () => {
  it('renders a ledger row resolving service + unit names and the cost snapshot', async () => {
    routeReads()
    render(<ConsumptionLedger />)

    await waitFor(() => {
      expect(screen.getByText('Ressonância Magnética')).toBeInTheDocument()
    })
    expect(screen.getByText('Unidade Centro')).toBeInTheDocument()
    expect(screen.getByText('R$ 45,00')).toBeInTheDocument()
    expect(screen.getByText('EXT-1')).toBeInTheDocument()
  })

  it('shows an empty state when there are no consumption records', async () => {
    routeReads([])
    render(<ConsumptionLedger />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhum consumo registrado/i)).toBeInTheDocument()
    })
  })

  it('shows an error state when the ledger fails to load', async () => {
    mockApiFetch.mockRejectedValue(new Error('down'))
    render(<ConsumptionLedger />)

    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar o consumo/i)).toBeInTheDocument()
    })
  })
})
