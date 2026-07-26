import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import SettlementsPage from './page'

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

const DRAFT = {
  id: 'set-1',
  professional: 'pro-1',
  professional_name: 'Dra. Ana Souza',
  competency: '2026-06',
  gross_amount: '10000.00',
  deductions: '500.00',
  net_amount: '9500.00',
  status: 'draft',
  calculated_at: '2026-07-01T10:00:00Z',
  paid_at: null,
}

const APPROVED = {
  id: 'set-2',
  professional: 'pro-2',
  professional_name: 'Dr. Bruno Lima',
  competency: '2026-06',
  gross_amount: '8000.00',
  deductions: '0.00',
  net_amount: '8000.00',
  status: 'approved',
  calculated_at: '2026-07-01T10:00:00Z',
  paid_at: null,
}

const PAID = {
  id: 'set-3',
  professional: 'pro-3',
  professional_name: 'Dra. Carla Dias',
  competency: '2026-05',
  gross_amount: '6000.00',
  deductions: '100.00',
  net_amount: '5900.00',
  status: 'paid',
  calculated_at: '2026-06-01T10:00:00Z',
  paid_at: '2026-06-10T10:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('SettlementsPage', () => {
  it('renders empty state when there are no settlements', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum repasse gerado ainda.')).toBeInTheDocument()
    })
  })

  it('renders rows from a paginated {results,count} payload', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: [DRAFT, APPROVED, PAID], count: 3 })

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })
    expect(screen.getByText('Dr. Bruno Lima')).toBeInTheDocument()
    expect(screen.getByText('Dra. Carla Dias')).toBeInTheDocument()

    // BRL formatting (net líquido) — NBSP inside pt-BR currency
    expect(screen.getByText(/R\$\s*9\.500,00/)).toBeInTheDocument()

    // Status badges
    expect(screen.getByText('Rascunho')).toBeInTheDocument()
    expect(screen.getByText('Aprovado')).toBeInTheDocument()
    expect(screen.getByText('Pago')).toBeInTheDocument()
  })

  it('renders rows from a bare array payload', async () => {
    mockApiFetch.mockResolvedValueOnce([DRAFT])

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })
  })

  it('shows the error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Network error'))

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar repasses.')).toBeInTheDocument()
    })
  })

  it('approves a draft settlement via POST .../approve/ (empty body)', async () => {
    mockApiFetch.mockResolvedValueOnce([DRAFT])

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))

    // Confirmation modal
    const confirm = await screen.findByRole('button', { name: 'Confirmar aprovação' })

    mockApiFetch.mockResolvedValueOnce({ ...DRAFT, status: 'approved' })
    fireEvent.click(confirm)

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url]) => url === '/api/v1/billing/settlements/set-1/approve/'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url]) => url === '/api/v1/billing/settlements/set-1/approve/'
    )!
    const [, init] = call
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()

    // Row transitions to approved (Pagar action now available)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pagar' })).toBeInTheDocument()
    })
  })

  it('pays an approved settlement via POST .../pay/ (empty body)', async () => {
    mockApiFetch.mockResolvedValueOnce([APPROVED])

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Dr. Bruno Lima')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Pagar' }))

    const confirm = await screen.findByRole('button', { name: 'Confirmar pagamento' })

    mockApiFetch.mockResolvedValueOnce({ ...APPROVED, status: 'paid' })
    fireEvent.click(confirm)

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(
        ([url]) => url === '/api/v1/billing/settlements/set-2/pay/'
      )
      expect(call).toBeTruthy()
    })

    const call = mockApiFetch.mock.calls.find(
      ([url]) => url === '/api/v1/billing/settlements/set-2/pay/'
    )!
    const [, init] = call
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  it('surfaces a maker-checker error from the approve action', async () => {
    mockApiFetch.mockResolvedValueOnce([DRAFT])

    render(<SettlementsPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
    const confirm = await screen.findByRole('button', { name: 'Confirmar aprovação' })

    mockApiFetch.mockRejectedValueOnce(new Error('403'))
    fireEvent.click(confirm)

    await waitFor(() => {
      expect(
        screen.getByText('Não foi possível concluir a ação. Verifique as permissões e tente novamente.')
      ).toBeInTheDocument()
    })
  })
})
