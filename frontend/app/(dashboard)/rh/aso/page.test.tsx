import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import AsoPage from './page'

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

const EXAM = {
  id: 'aso-1',
  employee: 'emp-1',
  exam_type: 'periodic',
  performed_on: '2026-01-10',
  expires_on: '2027-01-10',
  result: 'fit',
  provider_name: 'Dr. Carlos Nunes',
  recorded_by: 'user-1',
  created_at: '2026-01-10T10:00:00Z',
  updated_at: '2026-01-10T10:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AsoPage', () => {
  it('renders empty state when there are no exams', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/hr/occupational-health-exams/')) return Promise.resolve([])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<AsoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Nenhum ASO registrado/i)).toBeInTheDocument()
    })
  })

  it('renders exam rows when data loads', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/hr/occupational-health-exams/')) return Promise.resolve([EXAM])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<AsoPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Ana Souza').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Apto')).toBeInTheDocument()
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))

    render(<AsoPage />)

    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar ASOs/i)).toBeInTheDocument()
    })
  })

  it('opens the register modal and POSTs a new ASO', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (opts?.method === 'POST') return Promise.resolve({ id: 'aso-2' })
      if (url.startsWith('/api/v1/hr/occupational-health-exams/')) return Promise.resolve([EXAM])
      if (url.startsWith('/api/v1/hr/employees/')) return Promise.resolve(EMPLOYEES)
      return Promise.resolve([])
    })

    render(<AsoPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Ana Souza').length).toBeGreaterThan(0)
    })

    fireEvent.click(screen.getByRole('button', { name: /Novo ASO/ }))
    expect(await screen.findByLabelText(/Tipo de exame/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Funcionário/), { target: { value: 'emp-2' } })
    fireEvent.change(screen.getByLabelText(/Tipo de exame/), { target: { value: 'admission' } })
    fireEvent.change(screen.getByLabelText(/Data do exame/), { target: { value: '2026-07-01' } })
    fireEvent.change(screen.getByLabelText(/Médico/), { target: { value: 'Dra. Marta Reis' } })
    fireEvent.click(screen.getByRole('button', { name: /Registrar ASO/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(([, opts]) => opts?.method === 'POST')
      expect(postCall).toBeTruthy()
    })
    const postCall = mockApiFetch.mock.calls.find(([, opts]) => opts?.method === 'POST')!
    expect(postCall[0]).toBe('/api/v1/hr/occupational-health-exams/')
  })
})
