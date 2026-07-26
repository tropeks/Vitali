import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import MaintenanceCompleteModal from './MaintenanceCompleteModal'
import type { MaintenanceTicket } from './maintenanceMeta'

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

const TICKET: MaintenanceTicket = {
  id: 't1',
  asset: 'a1',
  facility: 'f1',
  description: 'Tela quebrada',
  status: 'IN_PROGRESS',
  cost: null,
  evidence_url: '',
  resolution: '',
  reported_by: null,
  assigned_to: null,
  started_at: '2024-03-01T10:00:00Z',
  completed_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MaintenanceCompleteModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <MaintenanceCompleteModal open={false} ticket={TICKET} onClose={vi.fn()} onSuccess={vi.fn()} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('POSTs resolution and cost to the complete endpoint', async () => {
    const completed = { ...TICKET, status: 'COMPLETED', resolution: 'Placa trocada', cost: '450.00' }
    mockApiFetch.mockResolvedValueOnce(completed)
    const onSuccess = vi.fn()
    const onClose = vi.fn()

    render(
      <MaintenanceCompleteModal open ticket={TICKET} onClose={onClose} onSuccess={onSuccess} />
    )

    fireEvent.change(screen.getByLabelText(/Resolução/i), {
      target: { value: 'Placa trocada' },
    })
    fireEvent.change(screen.getByLabelText(/Custo/i), { target: { value: '450.00' } })
    fireEvent.click(screen.getByRole('button', { name: /Concluir chamado/i }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/concession/maintenance-tickets/t1/complete/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ resolution: 'Placa trocada', cost: '450.00' })

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(completed))
    expect(onClose).toHaveBeenCalled()
  })

  it('allows completing without resolution/cost (both optional)', async () => {
    const completed = { ...TICKET, status: 'COMPLETED' }
    mockApiFetch.mockResolvedValueOnce(completed)

    render(
      <MaintenanceCompleteModal open ticket={TICKET} onClose={vi.fn()} onSuccess={vi.fn()} />
    )

    fireEvent.click(screen.getByRole('button', { name: /Concluir chamado/i }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [, init] = mockApiFetch.mock.calls[0]
    expect(JSON.parse(init.body)).toEqual({ resolution: '', cost: null })
  })

  it('shows an error message when the request fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))

    render(
      <MaintenanceCompleteModal open ticket={TICKET} onClose={vi.fn()} onSuccess={vi.fn()} />
    )

    fireEvent.click(screen.getByRole('button', { name: /Concluir chamado/i }))

    await waitFor(() => {
      expect(screen.getByText(/Erro ao concluir o chamado/i)).toBeInTheDocument()
    })
  })
})
