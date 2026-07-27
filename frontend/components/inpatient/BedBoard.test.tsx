import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import BedBoard from './BedBoard'

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
  units: [
    {
      id: 'u1',
      code: 'UTI',
      name: 'UTI Adulto',
      rooms: [
        {
          id: 'r1',
          name: 'Quarto 1',
          beds: [
            {
              id: 'b1',
              identifier: 'UTI-01',
              status: 'ocupado',
              patient: { id: 'p1', name: 'Maria Silva' },
            },
            { id: 'b2', identifier: 'UTI-02', status: 'livre', patient: null },
            { id: 'b3', identifier: 'UTI-03', status: 'higienizacao', patient: null },
          ],
        },
      ],
    },
  ],
}

const CENSUS = {
  occupancy: [],
  census: [
    {
      admission_id: 'a1',
      patient: { id: 'p1', name: 'Maria Silva' },
      bed: { id: 'b1', identifier: 'UTI-01' },
      unit: { id: 'u1', code: 'UTI', name: 'UTI Adulto' },
      admission_datetime: '2026-07-20T10:00:00Z',
      los_hours: 30,
    },
  ],
}

function routeApi(board: any = BOARD, census: any = CENSUS) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/beds/board/')) return Promise.resolve(board)
    if (url.startsWith('/api/v1/admissions/census/')) return Promise.resolve(census)
    return Promise.resolve({})
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BedBoard', () => {
  it('renders beds grouped by unit with status labels and the occupant name', async () => {
    routeApi()
    render(<BedBoard canTransfer={false} canDischarge={false} canAdmit={false} />)

    await waitFor(() => expect(screen.getByText('UTI-01')).toBeInTheDocument())
    // Unit grouping
    expect(screen.getByText('UTI Adulto')).toBeInTheDocument()
    // Occupant on the occupied bed
    expect(screen.getByText('Maria Silva')).toBeInTheDocument()
    // Status labels reflect the bed status enum
    expect(screen.getByText('Ocupado')).toBeInTheDocument()
    expect(screen.getByText('Livre')).toBeInTheDocument()
    expect(screen.getByText('Em higienização')).toBeInTheDocument()
    // LOS resolved from the census (30h → coarse "1d 6h")
    expect(screen.getByText(/Permanência: 1d 6h/)).toBeInTheDocument()
  })

  it('hides bed actions when the user lacks the permissions', async () => {
    routeApi()
    render(<BedBoard canTransfer={false} canDischarge={false} canAdmit={false} />)
    await waitFor(() => expect(screen.getByText('UTI-01')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Transferir' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Dar alta' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Admitir' })).not.toBeInTheDocument()
  })

  it('shows Transferir on an occupied bed and opens the transfer modal', async () => {
    routeApi()
    render(<BedBoard canTransfer canDischarge={false} canAdmit={false} />)
    await waitFor(() => expect(screen.getByText('UTI-01')).toBeInTheDocument())

    const transferBtn = screen.getByRole('button', { name: 'Transferir' })
    expect(transferBtn).toBeInTheDocument()
    fireEvent.click(transferBtn)
    expect(screen.getByRole('dialog', { name: 'Transferir leito' })).toBeInTheDocument()
  })

  it('shows Dar alta on an occupied bed with adt.discharge and opens the modal', async () => {
    routeApi()
    render(<BedBoard canTransfer={false} canDischarge canAdmit={false} />)
    await waitFor(() => expect(screen.getByText('UTI-01')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Dar alta' }))
    expect(screen.getByRole('dialog', { name: 'Dar alta' })).toBeInTheDocument()
  })

  it('shows Admitir on a livre bed with adt.admit', async () => {
    routeApi()
    render(<BedBoard canTransfer={false} canDischarge={false} canAdmit />)
    await waitFor(() => expect(screen.getByText('UTI-01')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Admitir' })).toBeInTheDocument()
  })

  it('shows an empty state when no beds are cadastrados', async () => {
    routeApi({ units: [] }, { occupancy: [], census: [] })
    render(<BedBoard canTransfer={false} canDischarge={false} canAdmit={false} />)
    await waitFor(() =>
      expect(screen.getByText('Nenhum leito cadastrado')).toBeInTheDocument()
    )
  })

  it('shows an error state when the board fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<BedBoard canTransfer={false} canDischarge={false} canAdmit={false} />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar o mapa de leitos')).toBeInTheDocument()
    )
  })
})
