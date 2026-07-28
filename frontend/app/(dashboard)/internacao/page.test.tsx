import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { hasPermission } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import InternacaoPage from './page'

vi.mock('@/lib/auth', () => ({
  hasPermission: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
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

const mockHasPermission = vi.mocked(hasPermission)
const mockApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockResolvedValue({ units: [], occupancy: [], census: [] })
})

describe('InternacaoPage', () => {
  it('blocks the panel entirely without beds.read', () => {
    mockHasPermission.mockReturnValue(false)
    render(<InternacaoPage />)
    expect(screen.getByText('Sem acesso ao painel de internação')).toBeInTheDocument()
    expect(screen.queryByText('Painel de Internação')).not.toBeInTheDocument()
  })

  it('renders the bed map and census with beds.read', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'beds.read')
    render(<InternacaoPage />)
    expect(screen.getByRole('heading', { name: 'Painel de Internação' })).toBeInTheDocument()
    expect(screen.getByText('Mapa de leitos')).toBeInTheDocument()
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/admissions/census/')
    )
  })
})
