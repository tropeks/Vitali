import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AssetMovementTimeline from './AssetMovementTimeline'

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

const MOVEMENTS = [
  {
    id: 'm1',
    movement_type: 'DEPLOYMENT',
    asset: 'a1',
    from_facility: null,
    to_facility: 'f1',
    swapped_with: null,
    performed_by: null,
    notes: 'Implantação inicial',
    created_at: '2024-03-01T10:00:00Z',
  },
  {
    id: 'm2',
    movement_type: 'TRANSFER',
    asset: 'a2',
    from_facility: 'f1',
    to_facility: 'f2',
    swapped_with: null,
    performed_by: null,
    notes: 'outro ativo',
    created_at: '2024-03-05T10:00:00Z',
  },
]

const FACILITIES = [
  { id: 'f1', name: 'Unidade Centro' },
  { id: 'f2', name: 'Unidade Norte' },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AssetMovementTimeline', () => {
  it('renders only movements for the given asset', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.startsWith('/api/v1/concession/asset-movements/')) return Promise.resolve(MOVEMENTS)
      return Promise.resolve([])
    })

    render(<AssetMovementTimeline assetId="a1" facilities={FACILITIES} />)

    await waitFor(() => {
      expect(screen.getByText('Implantação')).toBeInTheDocument()
    })
    // movement of asset a2 must not appear
    expect(screen.queryByText('Transferência')).not.toBeInTheDocument()
    expect(screen.getByText(/Implantação inicial/)).toBeInTheDocument()
  })

  it('shows empty state when no movements', async () => {
    mockApiFetch.mockResolvedValue([])
    render(<AssetMovementTimeline assetId="a1" facilities={FACILITIES} />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhuma movimenta/i)).toBeInTheDocument()
    })
  })
})
