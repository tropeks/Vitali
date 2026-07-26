import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import MaintenanceTicketFormModal from './MaintenanceTicketFormModal'
import type { AssetOption } from './maintenanceMeta'
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

const ASSETS: AssetOption[] = [
  { id: 'a1', asset_tag: 'PAT-001', name: 'Ultrassom Sala 1' },
  { id: 'a2', asset_tag: 'PAT-002', name: 'Tomógrafo' },
]

const FACILITIES: FacilityOption[] = [{ id: 'f1', name: 'Unidade Centro' }]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MaintenanceTicketFormModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <MaintenanceTicketFormModal
        open={false}
        assets={ASSETS}
        facilities={FACILITIES}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders asset and facility options when open', () => {
    render(
      <MaintenanceTicketFormModal
        open
        assets={ASSETS}
        facilities={FACILITIES}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    expect(screen.getByText('Novo ticket')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /PAT-001/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Unidade Centro' })).toBeInTheDocument()
  })

  it('disables submit until an asset and a description are set', () => {
    render(
      <MaintenanceTicketFormModal
        open
        assets={ASSETS}
        facilities={FACILITIES}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: /Criar ticket/i })).toBeDisabled()
  })

  it('POSTs the new ticket with asset, facility and description', async () => {
    const created = {
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
    mockApiFetch.mockResolvedValueOnce(created)
    const onSuccess = vi.fn()
    const onClose = vi.fn()

    render(
      <MaintenanceTicketFormModal
        open
        assets={ASSETS}
        facilities={FACILITIES}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    )

    fireEvent.change(screen.getByLabelText(/Ativo/i), { target: { value: 'a1' } })
    fireEvent.change(screen.getByLabelText(/Unidade/i), { target: { value: 'f1' } })
    fireEvent.change(screen.getByLabelText(/Descrição/i), {
      target: { value: 'Tela quebrada' },
    })

    fireEvent.click(screen.getByRole('button', { name: /Criar ticket/i }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/concession/maintenance-tickets/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      asset: 'a1',
      facility: 'f1',
      description: 'Tela quebrada',
    })

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(created))
    expect(onClose).toHaveBeenCalled()
  })

  it('shows a global error when the create request fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))

    render(
      <MaintenanceTicketFormModal
        open
        assets={ASSETS}
        facilities={FACILITIES}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    )

    fireEvent.change(screen.getByLabelText(/Ativo/i), { target: { value: 'a1' } })
    fireEvent.change(screen.getByLabelText(/Descrição/i), {
      target: { value: 'Tela quebrada' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Criar ticket/i }))

    await waitFor(() => {
      expect(screen.getByText(/Não foi possível criar o ticket/i)).toBeInTheDocument()
    })
  })
})
