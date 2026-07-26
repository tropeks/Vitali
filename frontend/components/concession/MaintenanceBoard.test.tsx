import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import MaintenanceBoard from './MaintenanceBoard'
import type { MaintenanceTicket, AssetOption } from './maintenanceMeta'
import type { FacilityOption } from './assetMeta'

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

const ASSETS: AssetOption[] = [{ id: 'a1', asset_tag: 'PAT-001', name: 'Ultrassom Sala 1' }]
const FACILITIES: FacilityOption[] = [{ id: 'f1', name: 'Unidade Centro' }]

const TICKET_OPEN: MaintenanceTicket = {
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

const TICKET_IN_PROGRESS: MaintenanceTicket = {
  ...TICKET_OPEN,
  id: 't2',
  status: 'IN_PROGRESS',
  started_at: '2024-03-01T10:00:00Z',
}

const TICKET_COMPLETED: MaintenanceTicket = {
  ...TICKET_OPEN,
  id: 't3',
  status: 'COMPLETED',
  cost: '450.00',
  evidence_url: 'https://example.com/foto.jpg',
  resolution: 'Placa trocada',
  completed_at: '2024-03-02T10:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MaintenanceBoard', () => {
  it('groups tickets into columns by status', () => {
    render(
      <MaintenanceBoard
        tickets={[TICKET_OPEN, TICKET_IN_PROGRESS, TICKET_COMPLETED]}
        assets={ASSETS}
        facilities={FACILITIES}
        onUpdated={vi.fn()}
      />
    )

    expect(screen.getByRole('heading', { name: 'Abertos' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Em andamento' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Concluídos' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Cancelados' })).toBeInTheDocument()

    // asset label rendered on each card
    expect(screen.getAllByText(/PAT-001/).length).toBe(3)
  })

  it('shows cost and evidence_url on a completed ticket card', () => {
    render(
      <MaintenanceBoard
        tickets={[TICKET_COMPLETED]}
        assets={ASSETS}
        facilities={FACILITIES}
        onUpdated={vi.fn()}
      />
    )

    expect(screen.getByText(/450,00/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /evid/i })).toHaveAttribute(
      'href',
      'https://example.com/foto.jpg'
    )
  })

  it('renders an Iniciar button for OPEN tickets that POSTs to /start/', async () => {
    const started = { ...TICKET_OPEN, status: 'IN_PROGRESS', started_at: '2024-03-01T10:00:00Z' }
    mockApiFetch.mockResolvedValueOnce(started)
    const onUpdated = vi.fn()

    render(
      <MaintenanceBoard
        tickets={[TICKET_OPEN]}
        assets={ASSETS}
        facilities={FACILITIES}
        onUpdated={onUpdated}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Iniciar/i }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/concession/maintenance-tickets/t1/start/')
    expect(init.method).toBe('POST')

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(started))
  })

  it('renders a Concluir button for IN_PROGRESS tickets that opens the complete modal', async () => {
    render(
      <MaintenanceBoard
        tickets={[TICKET_IN_PROGRESS]}
        assets={ASSETS}
        facilities={FACILITIES}
        onUpdated={vi.fn()}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Concluir/i }))

    expect(screen.getByRole('button', { name: /Concluir chamado/i })).toBeInTheDocument()

    const completed = { ...TICKET_IN_PROGRESS, status: 'COMPLETED' }
    mockApiFetch.mockResolvedValueOnce(completed)
    fireEvent.click(screen.getByRole('button', { name: /Concluir chamado/i }))

    await waitFor(() => {
      const [url, init] = mockApiFetch.mock.calls[0]
      expect(url).toBe('/api/v1/concession/maintenance-tickets/t2/complete/')
      expect(init.method).toBe('POST')
    })
  })

  it('does not render action buttons for COMPLETED or CANCELLED tickets', () => {
    render(
      <MaintenanceBoard
        tickets={[TICKET_COMPLETED]}
        assets={ASSETS}
        facilities={FACILITIES}
        onUpdated={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: /Iniciar/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Concluir$/i })).not.toBeInTheDocument()
  })

  it('shows an empty column hint when a status has no tickets', () => {
    render(
      <MaintenanceBoard tickets={[]} assets={ASSETS} facilities={FACILITIES} onUpdated={vi.fn()} />
    )
    const columns = screen.getAllByText('Nenhum chamado.')
    expect(columns.length).toBe(4)
  })
})
