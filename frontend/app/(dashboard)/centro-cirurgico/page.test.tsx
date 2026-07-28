import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { hasPermission } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import CentroCirurgicoPage from './page'

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
  mockApiFetch.mockResolvedValue({ date: '2026-07-24', rooms: [] })
})

describe('CentroCirurgicoPage', () => {
  it('blocks the page entirely without surgery.read', () => {
    mockHasPermission.mockReturnValue(false)
    render(<CentroCirurgicoPage />)
    expect(screen.getByText('Sem acesso ao centro cirúrgico')).toBeInTheDocument()
    expect(screen.queryByText('Centro Cirúrgico')).not.toBeInTheDocument()
  })

  it('renders the surgical board with surgery.read', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'surgery.read')
    render(<CentroCirurgicoPage />)
    expect(
      screen.getByRole('heading', { name: 'Centro Cirúrgico' })
    ).toBeInTheDocument()
    await waitFor(() =>
      expect(
        mockApiFetch.mock.calls.some(([url]) =>
          String(url).startsWith('/api/v1/surgical-cases/board/')
        )
      ).toBe(true)
    )
  })

  it('hides the Agendar action without surgery.schedule', async () => {
    mockHasPermission.mockImplementation((perm: string) => perm === 'surgery.read')
    render(<CentroCirurgicoPage />)
    await waitFor(() =>
      expect(screen.getByText('Nenhuma sala cirúrgica')).toBeInTheDocument()
    )
    expect(screen.queryByRole('button', { name: /Agendar/ })).not.toBeInTheDocument()
  })
})
