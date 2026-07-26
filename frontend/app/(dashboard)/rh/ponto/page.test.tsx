import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PontoPage from './page'

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

const EMPLOYEES = [
  { id: 'emp-1', full_name: 'Ana Souza' },
  { id: 'emp-2', full_name: 'Bruno Lima' },
]

const ENTRY = {
  id: 'te-1',
  employee: 'emp-1',
  event_type: 'in',
  occurred_at: '2026-07-24T08:00:00Z',
  source: 'web',
  recorded_by: 'user-1',
  created_at: '2026-07-24T08:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PontoPage', () => {
  it('renders empty state when there are no time entries', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/hr/time-entries/')) return Promise.resolve([])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<PontoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhuma marcação de ponto/i)).toBeInTheDocument()
    })
  })

  it('renders time entry rows when data loads', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/hr/time-entries/')) return Promise.resolve([ENTRY])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<PontoPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Ana Souza').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Entrada')).toBeInTheDocument()
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))

    render(<PontoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar marcações de ponto/i)).toBeInTheDocument()
    })
  })

  it('opens the register modal and POSTs a new marcação', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (opts?.method === 'POST') return Promise.resolve({ id: 'te-2' })
      if (url.startsWith('/api/v1/hr/time-entries/')) return Promise.resolve([ENTRY])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<PontoPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Ana Souza').length).toBeGreaterThan(0)
    })

    fireEvent.click(screen.getByRole('button', { name: /Registrar marcação/ }))
    expect(await screen.findByLabelText(/Tipo de marcação/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Funcionário/), { target: { value: 'emp-2' } })
    fireEvent.change(screen.getByLabelText(/Data\/hora/), {
      target: { value: '2026-07-24T09:00' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^Registrar$/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(([, opts]) => opts?.method === 'POST')
      expect(postCall).toBeTruthy()
    })
    const postCall = mockApiFetch.mock.calls.find(([, opts]) => opts?.method === 'POST')!
    expect(postCall[0]).toBe('/api/v1/hr/time-entries/')
  })

  it('filters the list by employee using the server query param', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/hr/time-entries/')) return Promise.resolve([ENTRY])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<PontoPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Ana Souza').length).toBeGreaterThan(0)
    })

    fireEvent.change(screen.getByLabelText(/Filtrar por funcionário/), {
      target: { value: 'emp-2' },
    })

    await waitFor(() => {
      const calls = mockApiFetch.mock.calls.filter(([url]) =>
        String(url).includes('/api/v1/hr/time-entries/')
      )
      const lastCall = calls[calls.length - 1]
      expect(lastCall?.[0]).toContain('employee=emp-2')
    })
  })
})
