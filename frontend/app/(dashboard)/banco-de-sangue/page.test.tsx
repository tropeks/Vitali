import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { hasPermission } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import BancoDeSanguePage from './page'

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

describe('BancoDeSanguePage', () => {
  it('blocks the page entirely without hemoterapia.read', () => {
    mockHasPermission.mockReturnValue(false)
    render(<BancoDeSanguePage />)
    expect(screen.getByText('Sem acesso ao banco de sangue')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Banco de Sangue' })).not.toBeInTheDocument()
  })

  it('renders the stock board by default with hemoterapia.read', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'hemoterapia.read')
    render(<BancoDeSanguePage />)
    expect(screen.getByRole('heading', { name: 'Banco de Sangue' })).toBeInTheDocument()
    await waitFor(() =>
      expect(
        mockApiFetch.mock.calls.some(([u]) => (u as string).startsWith('/api/v1/blood-bags/'))
      ).toBe(true)
    )
  })

  it('switches to the requisições tab', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'hemoterapia.read')
    render(<BancoDeSanguePage />)
    fireEvent.click(screen.getByRole('tab', { name: 'Requisições' }))
    await waitFor(() =>
      expect(
        mockApiFetch.mock.calls.some(([u]) =>
          (u as string).startsWith('/api/v1/transfusion-requests/')
        )
      ).toBe(true)
    )
  })
})
