import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ContasAPagarPage from './page'

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

const PAYABLE_PLANNED = {
  id: 'pay-1',
  external_id: 'nf-100',
  description: 'Aluguel da unidade centro',
  category: 'Ocupação',
  amount: '3500.00',
  due_date: '2026-08-10',
  paid_at: null,
  status: 'planned',
  notes: '',
  created_at: '2026-07-01T10:00:00Z',
  updated_at: '2026-07-01T10:00:00Z',
}
const PAYABLE_APPROVED = { ...PAYABLE_PLANNED, id: 'pay-2', description: 'Energia elétrica', amount: '890.50', status: 'approved' }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ContasAPagarPage', () => {
  it('renders empty state when no payables', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ContasAPagarPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhuma conta a pagar cadastrada.')).toBeInTheDocument()
    })
  })

  it('renders payable rows with BRL and status when data loads', async () => {
    mockApiFetch.mockResolvedValueOnce([PAYABLE_PLANNED, PAYABLE_APPROVED])
    render(<ContasAPagarPage />)
    await waitFor(() => {
      expect(screen.getByText('Aluguel da unidade centro')).toBeInTheDocument()
    })
    expect(screen.getByText('Energia elétrica')).toBeInTheDocument()
    expect(screen.getByText('R$ 3.500,00')).toBeInTheDocument()
    expect(screen.getByText('Prevista')).toBeInTheDocument()
    expect(screen.getByText('Aprovada')).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<ContasAPagarPage />)
    await waitFor(() => {
      expect(screen.getByText('Contas indisponíveis')).toBeInTheDocument()
    })
  })

  it('POSTs approve for a planned payable', async () => {
    mockApiFetch.mockResolvedValueOnce([PAYABLE_PLANNED])
    render(<ContasAPagarPage />)
    await waitFor(() => {
      expect(screen.getByText('Aluguel da unidade centro')).toBeInTheDocument()
    })
    mockApiFetch.mockResolvedValueOnce({ ...PAYABLE_PLANNED, status: 'approved' })
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(([url]) => url === '/api/v1/billing/payables/pay-1/approve/')
      expect(call).toBeTruthy()
      expect(call![1].method).toBe('POST')
    })
    await waitFor(() => expect(screen.getByText('Aprovada')).toBeInTheDocument())
  })

  it('POSTs a new payable through the create modal', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ContasAPagarPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhuma conta a pagar cadastrada.')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Nova conta' }))
    fireEvent.change(screen.getByLabelText('Descrição'), { target: { value: 'Material de escritório' } })
    fireEvent.change(screen.getByLabelText('Identificador'), { target: { value: 'nf-200' } })
    fireEvent.change(screen.getByLabelText('Valor'), { target: { value: '150.00' } })
    fireEvent.change(screen.getByLabelText('Vencimento'), { target: { value: '2026-08-20' } })

    mockApiFetch.mockResolvedValueOnce({
      ...PAYABLE_PLANNED,
      id: 'pay-9',
      external_id: 'nf-200',
      description: 'Material de escritório',
      amount: '150.00',
      due_date: '2026-08-20',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Criar' }))

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(([url]) => url === '/api/v1/billing/payables/')
      expect(call).toBeTruthy()
    })
    const call = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/billing/payables/' && init?.method === 'POST'
    )
    expect(call).toBeTruthy()
    expect(JSON.parse(call![1].body)).toMatchObject({
      external_id: 'nf-200',
      description: 'Material de escritório',
      amount: '150.00',
      due_date: '2026-08-20',
    })
  })
})
