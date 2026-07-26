import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import EscalasPage from './page'

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

const ROSTER = {
  id: 'r1',
  name: 'Escala UTI Agosto',
  facility: 'f1',
  start_date: '2026-08-01',
  end_date: '2026-08-31',
  active: true,
  created_at: '2026-07-01T10:00:00Z',
  updated_at: '2026-07-01T10:00:00Z',
}

const SLOT = {
  id: 's1',
  roster: 'r1',
  date: '2026-08-01',
  shift: 'morning',
  start_time: '07:00:00',
  end_time: '13:00:00',
  professional: 'p1',
  employee: null,
  unit: null,
  created_at: '2026-07-01T10:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

function routeMock(overrides: Partial<Record<'rosters' | 'slots', any>> = {}) {
  mockApiFetch.mockImplementation((path: string, opts?: any) => {
    if (path === '/api/v1/hr/duty-rosters/' && opts?.method === 'POST') {
      return Promise.resolve({ id: 'r-new' })
    }
    if (path.startsWith('/api/v1/hr/duty-rosters/')) {
      return overrides.rosters ?? Promise.resolve([])
    }
    if (path.startsWith('/api/v1/hr/roster-slots/')) {
      return overrides.slots ?? Promise.resolve([])
    }
    if (path.startsWith('/api/v1/organization/facilities/')) {
      return Promise.resolve([{ id: 'f1', name: 'Unidade Centro' }])
    }
    return Promise.resolve([])
  })
}

describe('EscalasPage', () => {
  it('renders the empty state when there are no rosters', async () => {
    routeMock()
    render(<EscalasPage />)
    await waitFor(() => {
      expect(screen.getByText('Nenhuma escala cadastrada ainda.')).toBeInTheDocument()
    })
  })

  it('renders rosters with their plantões when data loads', async () => {
    routeMock({ rosters: Promise.resolve([ROSTER]), slots: Promise.resolve([SLOT]) })
    render(<EscalasPage />)

    await waitFor(() => {
      expect(screen.getByText('Escala UTI Agosto')).toBeInTheDocument()
    })
    // Its plantão (morning shift) shows in the grid
    expect(screen.getByText('Manhã')).toBeInTheDocument()
    expect(screen.getByText('07:00–13:00')).toBeInTheDocument()
  })

  it('handles the paginated {results} response shape', async () => {
    routeMock({
      rosters: Promise.resolve({ results: [ROSTER], count: 1 }),
      slots: Promise.resolve({ results: [SLOT], count: 1 }),
    })
    render(<EscalasPage />)
    await waitFor(() => {
      expect(screen.getByText('Escala UTI Agosto')).toBeInTheDocument()
    })
  })

  it('shows the error state when loading fails', async () => {
    routeMock({ rosters: Promise.reject(new Error('boom')) })
    render(<EscalasPage />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar escalas.')).toBeInTheDocument()
    })
  })

  it('POSTs the exact body when creating a roster from the page', async () => {
    routeMock()
    render(<EscalasPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhuma escala cadastrada ainda.')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: /Nova escala/i })[0])

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Unidade Centro' })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Nome da escala/i), {
      target: { value: 'Escala Pronto-Socorro' },
    })
    fireEvent.change(screen.getByLabelText(/Unidade/i), { target: { value: 'f1' } })
    fireEvent.change(screen.getByLabelText(/Início/i), { target: { value: '2026-09-01' } })
    fireEvent.change(screen.getByLabelText(/Fim/i), { target: { value: '2026-09-30' } })

    fireEvent.click(screen.getByRole('button', { name: /Criar escala/i }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        (c) => c[0] === '/api/v1/hr/duty-rosters/' && c[1]?.method === 'POST'
      )
      expect(postCall).toBeTruthy()
      expect(JSON.parse(postCall![1].body)).toEqual({
        name: 'Escala Pronto-Socorro',
        facility: 'f1',
        start_date: '2026-09-01',
        end_date: '2026-09-30',
        active: true,
      })
    })
  })
})
