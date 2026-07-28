import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { hasPermission } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import ProntoSocorroPage from './page'

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
  mockApiFetch.mockResolvedValue({
    queue: [],
    counts: { vermelho: 0, laranja: 0, amarelo: 0, verde: 0, azul: 0 },
    overdue: 0,
    unclassified: 0,
    total: 0,
  })
})

describe('ProntoSocorroPage', () => {
  it('blocks the panel entirely without emergency.read', () => {
    mockHasPermission.mockReturnValue(false)
    render(<ProntoSocorroPage />)
    expect(screen.getByText('Sem acesso ao pronto-socorro')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Pronto-Socorro' })).not.toBeInTheDocument()
  })

  it('renders the PS queue with emergency.read', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'emergency.read')
    render(<ProntoSocorroPage />)
    expect(screen.getByRole('heading', { name: 'Pronto-Socorro' })).toBeInTheDocument()
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/emergency-encounters/board/'),
    )
    // Without emergency.manage the Abrir boletim action stays hidden.
    expect(screen.queryByRole('button', { name: 'Abrir boletim' })).not.toBeInTheDocument()
  })
})
