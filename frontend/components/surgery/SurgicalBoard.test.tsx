import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import SurgicalBoard from './SurgicalBoard'

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

const mockApiFetch = vi.mocked(apiFetch)

const BOARD = {
  date: '2026-07-24',
  rooms: [
    {
      id: 'or1',
      code: 'SO-01',
      name: 'Sala 1',
      cases: [
        {
          id: 'c1',
          patient: { id: 'p1', name: 'Maria Silva' },
          surgeon: { id: 's1', name: 'Dr. Ana Souza' },
          scheduled_start: '2026-07-24T11:00:00Z',
          scheduled_end: '2026-07-24T12:30:00Z',
          status: 'agendada',
          priority: 'urgencia',
          procedures: [{ tuss_code: '30731100', description: 'Apendicectomia', quantity: 1 }],
        },
      ],
    },
    { id: 'or2', code: 'SO-02', name: 'Sala 2', cases: [] },
  ],
}

const FACILITIES = [{ id: 'f1', name: 'Hospital Central' }]

function routeApi(board: any = BOARD) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url.startsWith('/api/v1/surgical-cases/board/')) return Promise.resolve(board)
    if (url.startsWith('/api/v1/organization/facilities/')) return Promise.resolve(FACILITIES)
    if (url.includes('/confirm/') && opts?.method === 'POST') return Promise.resolve({})
    if (url.includes('/surgical-cases/?status=agendada')) return Promise.resolve([])
    return Promise.resolve({})
  })
}

function boardCalls(): string[] {
  return mockApiFetch.mock.calls
    .map((c) => c[0] as string)
    .filter((u) => u.startsWith('/api/v1/surgical-cases/board/'))
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SurgicalBoard', () => {
  it('renders rooms and cases coloured by status with the priority accent', async () => {
    routeApi()
    render(<SurgicalBoard canSchedule={false} canManage={false} />)

    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    // Rooms as columns (including the empty one)
    expect(screen.getByText('Sala 1')).toBeInTheDocument()
    expect(screen.getByText('Sala 2')).toBeInTheDocument()
    expect(screen.getByText('Nenhuma cirurgia agendada.')).toBeInTheDocument()
    // Status + priority surfaced
    expect(screen.getByText('Agendada')).toBeInTheDocument()
    expect(screen.getByText('Urgência')).toBeInTheDocument()
    expect(screen.getByText('Dr. Ana Souza')).toBeInTheDocument()
  })

  it('refetches the board when navigating to the next day', async () => {
    routeApi()
    render(<SurgicalBoard canSchedule={false} canManage={false} />)
    await waitFor(() => expect(boardCalls().length).toBe(1))
    const first = boardCalls()[0]

    fireEvent.click(screen.getByRole('button', { name: 'Próximo dia' }))
    await waitFor(() => expect(boardCalls().length).toBe(2))
    expect(boardCalls()[1]).not.toBe(first)
    expect(boardCalls()[1]).toMatch(/date=/)
  })

  it('hides Agendar and the per-case actions without surgery.schedule', async () => {
    routeApi()
    render(<SurgicalBoard canSchedule={false} canManage={false} />)
    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Agendar/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument()
  })

  it('opens the schedule modal from Agendar with surgery.schedule', async () => {
    routeApi()
    render(<SurgicalBoard canSchedule canManage={false} />)
    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Agendar/ }))
    expect(screen.getByRole('dialog', { name: 'Agendar cirurgia' })).toBeInTheDocument()
  })

  it('confirms a case with a POST to the confirm action', async () => {
    routeApi()
    render(<SurgicalBoard canSchedule canManage={false} />)
    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))
    await waitFor(() =>
      expect(
        mockApiFetch.mock.calls.some(
          ([url, opts]) =>
            url === '/api/v1/surgical-cases/c1/confirm/' && (opts as any)?.method === 'POST'
        )
      ).toBe(true)
    )
  })

  it('opens the cancel modal from a case block', async () => {
    routeApi()
    render(<SurgicalBoard canSchedule canManage={false} />)
    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.getByRole('dialog', { name: 'Cancelar cirurgia' })).toBeInTheDocument()
  })

  it('shows an empty state when there are no rooms', async () => {
    routeApi({ date: '2026-07-24', rooms: [] })
    render(<SurgicalBoard canSchedule={false} canManage={false} />)
    await waitFor(() =>
      expect(screen.getByText('Nenhuma sala cirúrgica')).toBeInTheDocument()
    )
  })

  it('shows an error state when the board fetch fails', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/surgical-cases/board/')) return Promise.reject(new Error('boom'))
      return Promise.resolve([])
    })
    render(<SurgicalBoard canSchedule={false} canManage={false} />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar o mapa cirúrgico')).toBeInTheDocument()
    )
  })
})
