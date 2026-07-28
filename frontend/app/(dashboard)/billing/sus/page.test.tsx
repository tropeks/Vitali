import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { hasPermission } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import FaturamentoSusPage from './page'

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
  mockApiFetch.mockResolvedValue([])
})

describe('FaturamentoSusPage', () => {
  it('blocks the whole page without sus.read', () => {
    mockHasPermission.mockReturnValue(false)
    render(<FaturamentoSusPage />)
    expect(screen.getByText('Sem acesso ao Faturamento SUS')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Faturamento SUS' })).not.toBeInTheDocument()
  })

  it('renders the competência list with sus.read', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'sus.read')
    render(<FaturamentoSusPage />)
    expect(screen.getByRole('heading', { name: 'Faturamento SUS' })).toBeInTheDocument()
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/billing/sus-competencias/'),
    )
    // Without sus.write there is no "Nova competência" form.
    expect(screen.queryByText('Nova competência')).not.toBeInTheDocument()
  })
})
