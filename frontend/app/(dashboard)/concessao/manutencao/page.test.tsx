import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ManutencaoPage from './page'

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

const ASSET_1 = { id: 'a1', asset_tag: 'PAT-001', name: 'Ultrassom Sala 1', model: 'GE Vivid E95' }
const FACILITY_1 = { id: 'f1', name: 'Unidade Centro' }

const TICKET_OPEN = {
  id: 't1',
  asset: 'a1',
  facility: 'f1',
  description: 'Tela quebrada',
  status: 'OPEN',
  cost: null,
  evidence_url: '',
  resolution: '',
  reported_by: null,
  assigned_to: null,
  started_at: null,
  completed_at: null,
}

function mockList(tickets: any) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/concession/maintenance-tickets/')) return Promise.resolve(tickets)
    if (path.startsWith('/api/v1/concession/assets/')) return Promise.resolve([ASSET_1])
    if (path === '/api/v1/organization/facilities/') return Promise.resolve([FACILITY_1])
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('ManutencaoPage', () => {
  it('renders empty state when no tickets', async () => {
    mockList([])
    render(<ManutencaoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhum ticket de manutenção cadastrado/i)).toBeInTheDocument()
    })
  })

  it('renders the board with ticket cards when data loads', async () => {
    mockList([TICKET_OPEN])
    render(<ManutencaoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Tela quebrada/)).toBeInTheDocument()
    })
    expect(screen.getByText('Abertos')).toBeInTheDocument()
  })

  it('shows an error state when the tickets fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))
    render(<ManutencaoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar os tickets de manutenção/i)).toBeInTheDocument()
    })
  })

  it('handles paginated {results,count} envelope', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.startsWith('/api/v1/concession/maintenance-tickets/'))
        return Promise.resolve({ count: 1, results: [TICKET_OPEN] })
      if (path.startsWith('/api/v1/concession/assets/')) return Promise.resolve([ASSET_1])
      if (path === '/api/v1/organization/facilities/') return Promise.resolve([FACILITY_1])
      return Promise.resolve([])
    })
    render(<ManutencaoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Tela quebrada/)).toBeInTheDocument()
    })
  })

  it('opens the create form when clicking + Novo ticket', async () => {
    mockList([TICKET_OPEN])
    render(<ManutencaoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Tela quebrada/)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Novo ticket/i }))

    expect(screen.getByRole('button', { name: /Criar ticket/i })).toBeInTheDocument()
  })

  it('reloads the ticket list after starting a ticket', async () => {
    mockList([TICKET_OPEN])
    render(<ManutencaoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Tela quebrada/)).toBeInTheDocument()
    })

    const started = { ...TICKET_OPEN, status: 'IN_PROGRESS', started_at: '2024-03-01T10:00:00Z' }
    mockApiFetch.mockImplementation((path: string, init?: any) => {
      if (init?.method === 'POST' && path.endsWith('/start/')) return Promise.resolve(started)
      if (path.startsWith('/api/v1/concession/maintenance-tickets/'))
        return Promise.resolve([started])
      if (path.startsWith('/api/v1/concession/assets/')) return Promise.resolve([ASSET_1])
      if (path === '/api/v1/organization/facilities/') return Promise.resolve([FACILITY_1])
      return Promise.resolve([])
    })

    fireEvent.click(screen.getByRole('button', { name: /Iniciar/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Em andamento' })).toBeInTheDocument()
      expect(screen.getByText('Em andamento', { selector: 'span' })).toBeInTheDocument()
    })
  })
})
