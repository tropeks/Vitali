import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { ApiError } from '@/lib/api'
import EmergencyCaseDetail from './EmergencyCaseDetail'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

const OLDER = {
  id: 'rc-0',
  boletim: 'bol-1',
  flowchart: 'fc-1',
  flowchart_code: 'DOR-TORAX',
  discriminator: 'disc-0',
  discriminator_code: 'DESCONFORTO',
  acuity_level: 'amarelo',
  target_minutes: 60,
  classified_at: '2026-07-25T12:40:00Z',
  notes: 'triagem inicial',
}

const CURRENT = {
  id: 'rc-1',
  boletim: 'bol-1',
  flowchart: 'fc-1',
  flowchart_code: 'DOR-TORAX',
  discriminator: 'disc-1',
  discriminator_code: 'DOR-PRECORDIAL',
  acuity_level: 'laranja',
  target_minutes: 10,
  classified_at: '2026-07-25T13:00:00Z',
  notes: 're-triagem',
}

const BOLETIM = {
  id: 'bol-1',
  patient: 'patient-1',
  arrival_at: '2026-07-25T12:30:00Z',
  mode_of_arrival: 'ambulancia',
  chief_complaint: 'Dor no peito',
  status: 'classificado',
  disposition: null,
  admission: null,
  current_classification: CURRENT,
}

function routeApi(over: { boletim?: any; history?: any; closeError?: number } = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url === '/api/v1/emergency-encounters/bol-1/' && !opts) {
      return Promise.resolve(over.boletim ?? BOLETIM)
    }
    if (url.startsWith('/api/v1/risk-classifications/?boletim=')) {
      return Promise.resolve(over.history ?? [CURRENT, OLDER])
    }
    if (url === '/api/v1/beds/?status=livre') {
      return Promise.resolve([{ id: 'bed-1', identifier: 'L-01', status: 'livre' }])
    }
    if (url === '/api/v1/emergency-encounters/bol-1/close/') {
      if (over.closeError) return Promise.reject(new ApiError(over.closeError, {}))
      return Promise.resolve({ ...BOLETIM, status: 'encerrado', disposition: 'alta' })
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('EmergencyCaseDetail', () => {
  it('shows arrival data + highlighted current acuity', async () => {
    routeApi()
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify canManage onBack={() => {}} />,
    )
    await waitFor(() => {
      expect(screen.getByText('Atendimento de emergência')).toBeInTheDocument()
    })
    // Current acuity destaque (laranja from current_classification) — also
    // appears as the top history entry, so at least one is present.
    expect(screen.getAllByText('Laranja (muito urgente)').length).toBeGreaterThan(0)
    expect(screen.getByText(/Dor no peito/)).toBeInTheDocument()
  })

  it('renders the append-only classification history (newest first)', async () => {
    routeApi()
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify canManage onBack={() => {}} />,
    )
    await waitFor(() => {
      expect(
        screen.getByLabelText('Histórico de classificações de risco'),
      ).toBeInTheDocument()
    })
    const historyList = within(screen.getByLabelText('Histórico de classificações de risco'))
    // Both the current and the older triagem appear (append-only).
    expect(historyList.getByText(/DOR-PRECORDIAL/)).toBeInTheDocument()
    expect(historyList.getByText(/DESCONFORTO/)).toBeInTheDocument()
    // The newest entry is flagged "Atual".
    expect(historyList.getByText('Atual')).toBeInTheDocument()
  })

  it('hides Reclassificar without emergency.classify', async () => {
    routeApi()
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify={false} canManage onBack={() => {}} />,
    )
    await waitFor(() => {
      expect(screen.getByText('Atendimento de emergência')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Reclassificar' })).not.toBeInTheDocument()
    // Desfecho (manage) still shown.
    expect(screen.getByRole('button', { name: 'Desfecho' })).toBeInTheDocument()
  })

  it('hides Desfecho without emergency.manage', async () => {
    routeApi()
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify canManage={false} onBack={() => {}} />,
    )
    await waitFor(() => {
      expect(screen.getByText('Atendimento de emergência')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Desfecho' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reclassificar' })).toBeInTheDocument()
  })

  it('posts the desfecho (close) and refreshes', async () => {
    routeApi()
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify canManage onBack={() => {}} />,
    )
    await waitFor(() => screen.getByRole('button', { name: 'Desfecho' }))

    fireEvent.click(screen.getByRole('button', { name: 'Desfecho' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar desfecho' }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/bol-1/close/',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('surfaces a 409 on close (leito ocupado / transição ilegal)', async () => {
    routeApi({ closeError: 409 })
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify canManage onBack={() => {}} />,
    )
    await waitFor(() => screen.getByRole('button', { name: 'Desfecho' }))

    fireEvent.click(screen.getByRole('button', { name: 'Desfecho' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar desfecho' }))

    await waitFor(() => {
      expect(
        screen.getByText(/leito ocupado ou transição inválida/i),
      ).toBeInTheDocument()
    })
  })

  it('shows the disposition for an encerrado boletim (with internação hint)', async () => {
    routeApi({
      boletim: {
        ...BOLETIM,
        status: 'encerrado',
        disposition: 'internacao',
        admission: 'adm-9',
      },
    })
    render(
      <EmergencyCaseDetail boletimId="bol-1" canClassify canManage onBack={() => {}} />,
    )
    await waitFor(() => {
      expect(screen.getByText('Encerrado')).toBeInTheDocument()
    })
    expect(screen.getByText('Internação')).toBeInTheDocument()
    expect(screen.getByText(/adm-9/)).toBeInTheDocument()
    // Write actions are gone once closed.
    expect(screen.queryByRole('button', { name: 'Reclassificar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Desfecho' })).not.toBeInTheDocument()
  })
})
