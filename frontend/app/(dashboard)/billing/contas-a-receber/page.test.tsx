import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ContasAReceberPage from './page'

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

const RECEIVABLE_OPEN = {
  id: 'rec-1',
  guide_number: 'G-555',
  patient_name: 'Maria Oliveira',
  provider_name: 'Unimed',
  amount: '1200.00',
  due_date: '2026-08-05',
  received_at: null,
  status: 'billed',
  notes: '',
  created_at: '2026-07-01T10:00:00Z',
  updated_at: '2026-07-01T10:00:00Z',
}
const RECEIVABLE_DONE = { ...RECEIVABLE_OPEN, id: 'rec-2', patient_name: 'João Costa', status: 'received' }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ContasAReceberPage', () => {
  it('renders empty state when no receivables', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ContasAReceberPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhuma conta a receber cadastrada.')).toBeInTheDocument()
    })
  })

  it('renders receivable rows with payer, BRL and status', async () => {
    mockApiFetch.mockResolvedValueOnce([RECEIVABLE_OPEN, RECEIVABLE_DONE])
    render(<ContasAReceberPage />)
    await waitFor(() => {
      expect(screen.getByText('Maria Oliveira')).toBeInTheDocument()
    })
    expect(screen.getByText('João Costa')).toBeInTheDocument()
    expect(screen.getAllByText('Unimed').length).toBeGreaterThan(0)
    expect(screen.getAllByText('R$ 1.200,00').length).toBe(2)
    expect(screen.getByText('Faturado')).toBeInTheDocument()
    expect(screen.getByText('Recebido')).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<ContasAReceberPage />)
    await waitFor(() => {
      expect(screen.getByText('Contas indisponíveis')).toBeInTheDocument()
    })
  })

  it('POSTs mark_received (baixa) on an open receivable', async () => {
    mockApiFetch.mockResolvedValueOnce([RECEIVABLE_OPEN])
    render(<ContasAReceberPage />)
    await waitFor(() => {
      expect(screen.getByText('Maria Oliveira')).toBeInTheDocument()
    })
    mockApiFetch.mockResolvedValueOnce({ ...RECEIVABLE_OPEN, status: 'received' })
    fireEvent.click(screen.getByRole('button', { name: 'Dar baixa' }))
    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url]) => url === '/api/v1/billing/receivables/rec-1/mark_received/'
      )
      expect(call).toBeTruthy()
      expect(call![1].method).toBe('POST')
    })
    await waitFor(() => expect(screen.getByText('Recebido')).toBeInTheDocument())
  })
})
