import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import AssetMovementModal from './AssetMovementModal'

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

const ASSET = {
  id: 'a1',
  asset_tag: 'PAT-001',
  name: 'Ultrassom',
  model: 'GE',
  serial_number: 'SN-1',
  status: 'ACTIVE' as const,
  ownership: 'OPERATOR' as const,
  purchase_cost: '120000.00',
  useful_life_months: 60,
  purchase_date: '2024-01-01',
  current_location: 'f1',
  active: true,
  monthly_depreciation: '2000.00',
}

const FACILITIES = [
  { id: 'f1', name: 'Unidade Centro' },
  { id: 'f2', name: 'Unidade Norte' },
]

function mockFacilitiesThenPost() {
  mockApiFetch.mockImplementation((path: string, opts?: any) => {
    if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
    if (path === '/api/v1/concession/asset-movements/' && opts?.method === 'POST')
      return Promise.resolve({ id: 'm-new' })
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AssetMovementModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <AssetMovementModal open={false} asset={ASSET} onClose={() => {}} onSuccess={() => {}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('POSTs a TRANSFER movement with from/to facility', async () => {
    mockFacilitiesThenPost()
    const onSuccess = vi.fn()

    render(<AssetMovementModal open asset={ASSET} onClose={() => {}} onSuccess={onSuccess} />)

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Unidade Norte' })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Tipo de movimenta/i), { target: { value: 'TRANSFER' } })
    fireEvent.change(screen.getByLabelText(/Origem/i), { target: { value: 'f1' } })
    fireEvent.change(screen.getByLabelText(/Destino/i), { target: { value: 'f2' } })

    fireEvent.click(screen.getByRole('button', { name: /Registrar movimenta/i }))

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled()
    })

    const postCall = mockApiFetch.mock.calls.find(
      (c) => c[0] === '/api/v1/concession/asset-movements/' && c[1]?.method === 'POST'
    )
    expect(postCall).toBeTruthy()
    expect(JSON.parse(postCall![1].body)).toEqual({
      movement_type: 'TRANSFER',
      asset: 'a1',
      from_facility: 'f1',
      to_facility: 'f2',
      swapped_with: null,
      notes: '',
    })
  })
})
