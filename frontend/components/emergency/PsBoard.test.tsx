import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import PsBoard from './PsBoard'

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
  queue: [
    {
      boletim_id: 'b-unc',
      patient: { id: 'p1', name: 'Ana Ambulante' },
      status: 'aguardando_classificacao',
      mode_of_arrival: 'ambulante',
      chief_complaint: 'Dor de cabeça',
      arrival_at: '2026-07-28T10:00:00Z',
      waited_minutes: 5,
      acuity_level: null,
      target_minutes: null,
      overdue: false,
    },
    {
      boletim_id: 'b-red',
      patient: { id: 'p2', name: 'Bruno Grave' },
      status: 'classificado',
      mode_of_arrival: 'ambulancia',
      chief_complaint: 'Dor torácica',
      arrival_at: '2026-07-28T09:30:00Z',
      waited_minutes: 40,
      acuity_level: 'vermelho',
      target_minutes: 0,
      overdue: true,
    },
    {
      boletim_id: 'b-green',
      patient: { id: 'p3', name: 'Carla Leve' },
      status: 'classificado',
      mode_of_arrival: 'maca',
      chief_complaint: 'Corte no dedo',
      arrival_at: '2026-07-28T09:50:00Z',
      waited_minutes: 15,
      acuity_level: 'verde',
      target_minutes: 120,
      overdue: false,
    },
  ],
  counts: { vermelho: 1, laranja: 0, amarelo: 0, verde: 1, azul: 0 },
  overdue: 1,
  unclassified: 1,
  total: 3,
}

function routeApi(board: any = BOARD) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/emergency-encounters/board/')) return Promise.resolve(board)
    return Promise.resolve({})
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PsBoard', () => {
  it('renders the queue coloured by acuidade with the overdue highlight and counts', async () => {
    routeApi()
    render(<PsBoard canManage={false} canClassify={false} />)

    await waitFor(() => expect(screen.getByText('Bruno Grave')).toBeInTheDocument())

    // Rows rendered
    expect(screen.getByText('Ana Ambulante')).toBeInTheDocument()
    expect(screen.getByText('Carla Leve')).toBeInTheDocument()

    // Acuity coloured row for the vermelho boletim
    const redRow = screen.getByLabelText('Boletim de Bruno Grave')
    expect(redRow.className).toContain('bg-red-50')
    // Overdue highlight
    expect(redRow.className).toContain('ring-red-400')
    expect(within(redRow).getByText('Tempo-alvo estourado')).toBeInTheDocument()

    // Unclassified boletim is neutral grey
    const uncRow = screen.getByLabelText('Boletim de Ana Ambulante')
    expect(uncRow.className).toContain('bg-slate-50')

    // Counts header (per-acuity + total)
    const header = screen.getByText('Total').closest('span')!
    expect(within(header).getByText('3')).toBeInTheDocument()
  })

  it('hides Abrir boletim + row actions without emergency.manage/classify', async () => {
    routeApi()
    render(<PsBoard canManage={false} canClassify={false} />)
    await waitFor(() => expect(screen.getByText('Bruno Grave')).toBeInTheDocument())

    expect(screen.queryByRole('button', { name: 'Abrir boletim' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Classificar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Chamar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Desfecho' })).not.toBeInTheDocument()
  })

  it('shows Classificar (emergency.classify) on classifiable boletins', async () => {
    routeApi()
    render(<PsBoard canManage={false} canClassify />)
    await waitFor(() => expect(screen.getByText('Ana Ambulante')).toBeInTheDocument())

    // Both the aguardando and the classificado rows can be (re)classified.
    expect(screen.getAllByRole('button', { name: 'Classificar' }).length).toBe(3)
  })

  it('opens the Abrir boletim modal with emergency.manage', async () => {
    routeApi()
    render(<PsBoard canManage canClassify={false} />)
    await waitFor(() => expect(screen.getByText('Bruno Grave')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Abrir boletim' }))
    expect(screen.getByRole('dialog', { name: 'Abrir boletim' })).toBeInTheDocument()
  })

  it('posts start-attendance when Chamar is clicked on a classificado boletim', async () => {
    routeApi()
    render(<PsBoard canManage canClassify={false} />)
    await waitFor(() => expect(screen.getByText('Bruno Grave')).toBeInTheDocument())

    // Chamar only shows on classificado rows (Bruno + Carla), not the unclassified.
    const chamarButtons = screen.getAllByRole('button', { name: 'Chamar' })
    expect(chamarButtons.length).toBe(2)
    fireEvent.click(chamarButtons[0])

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/b-red/start-attendance/',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })

  it('shows a friendly error when Chamar hits a 409 (illegal transition)', async () => {
    const { ApiError } = await import('@/lib/api')
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/start-attendance/')) {
        return Promise.reject(new ApiError(409, { detail: 'ilegal' }))
      }
      if (url.startsWith('/api/v1/emergency-encounters/board/')) return Promise.resolve(BOARD)
      return Promise.resolve({})
    })
    render(<PsBoard canManage canClassify={false} />)
    await waitFor(() => expect(screen.getByText('Bruno Grave')).toBeInTheDocument())

    fireEvent.click(screen.getAllByRole('button', { name: 'Chamar' })[0])
    await waitFor(() =>
      expect(
        screen.getByText('Não é possível chamar este paciente na situação atual.'),
      ).toBeInTheDocument(),
    )
  })

  it('opens Classificar and Desfecho modals from a row', async () => {
    routeApi()
    render(<PsBoard canManage canClassify />)
    await waitFor(() => expect(screen.getByText('Bruno Grave')).toBeInTheDocument())

    fireEvent.click(screen.getAllByRole('button', { name: 'Classificar' })[0])
    expect(screen.getByRole('dialog', { name: 'Classificar risco' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Fechar' }))

    fireEvent.click(screen.getAllByRole('button', { name: 'Desfecho' })[0])
    expect(screen.getByRole('dialog', { name: 'Registrar desfecho' })).toBeInTheDocument()
  })

  it('shows an empty state when the queue is empty', async () => {
    routeApi({ queue: [], counts: { vermelho: 0, laranja: 0, amarelo: 0, verde: 0, azul: 0 }, overdue: 0, unclassified: 0, total: 0 })
    render(<PsBoard canManage={false} canClassify={false} />)
    await waitFor(() => expect(screen.getByText('Fila vazia')).toBeInTheDocument())
  })

  it('shows an error state when the board fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<PsBoard canManage={false} canClassify={false} />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar a fila do pronto-socorro')).toBeInTheDocument(),
    )
  })
})
