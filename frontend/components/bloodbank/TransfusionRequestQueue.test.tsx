import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import TransfusionRequestQueue from './TransfusionRequestQueue'

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

function req(over: Partial<any> = {}) {
  return {
    id: 'r1',
    patient: 'p1',
    component: 7,
    component_display: 'Concentrado de Hemácias',
    quantidade: 2,
    indicacao: 'Anemia grave',
    urgencia: 'urgencia',
    requester: 'prof1',
    status: 'solicitada',
    crossmatches: [],
    ...over,
  }
}

const RESERVED = req({
  id: 'r2',
  status: 'reservada',
  urgencia: 'rotina',
  crossmatches: [
    {
      id: 'xm1',
      request: 'r2',
      bag: 'bag-1',
      bag_identifier: 'DIN-100',
      abo_compativel: true,
      rh_compativel: true,
      crossmatch_resultado: 'compativel',
      compativel: true,
    },
  ],
})

function requestCalls(): string[] {
  return mockApiFetch.mock.calls
    .map((c) => c[0] as string)
    .filter((u) => u.startsWith('/api/v1/transfusion-requests/') && !u.includes('/liberar/'))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockResolvedValue([req(), RESERVED])
})

describe('TransfusionRequestQueue', () => {
  it('renders requests with status, urgência and the crossmatch when reservada', async () => {
    render(<TransfusionRequestQueue canManage={false} canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())

    expect(screen.getByText('Solicitada')).toBeInTheDocument()
    expect(screen.getByText('Reservada')).toBeInTheDocument()
    expect(screen.getByText('Urgência')).toBeInTheDocument()
    // crossmatch surfaced on the reserved request
    expect(screen.getByText('Prova cruzada: compatível')).toBeInTheDocument()
    expect(screen.getByText('Bolsa DIN-100')).toBeInTheDocument()
  })

  it('refetches with the status filter param', async () => {
    render(<TransfusionRequestQueue canManage={false} canRequest={false} />)
    await waitFor(() => expect(requestCalls().length).toBe(1))
    fireEvent.change(screen.getByLabelText('Filtrar requisições por situação'), {
      target: { value: 'reservada' },
    })
    await waitFor(() => expect(requestCalls().some((u) => u.includes('status=reservada'))).toBe(true))
  })

  it('hides the agency actions without hemoterapia.manage', async () => {
    render(<TransfusionRequestQueue canManage={false} canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Reservar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Liberar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()
  })

  it('shows the right agency action per status with hemoterapia.manage', async () => {
    render(<TransfusionRequestQueue canManage canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())
    // solicitada → Reservar + Cancelar; reservada → Liberar + Cancelar
    expect(screen.getByRole('button', { name: 'Reservar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Liberar' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Cancelar' }).length).toBe(2)
  })

  it('opens the reserve modal for a solicitada request', async () => {
    render(<TransfusionRequestQueue canManage canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Reservar' }))
    expect(screen.getByRole('dialog', { name: 'Reservar bolsa' })).toBeInTheDocument()
  })

  it('liberates a reserved request via a direct POST', async () => {
    render(<TransfusionRequestQueue canManage canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r2')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Liberar' }))
    await waitFor(() =>
      expect(
        mockApiFetch.mock.calls.some(
          ([url, opts]) =>
            url === '/api/v1/transfusion-requests/r2/liberar/' && (opts as any)?.method === 'POST'
        )
      ).toBe(true)
    )
  })

  it('surfaces a 409 on liberar as an action error', async () => {
    const { ApiError } = await import('@/lib/api')
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/liberar/') && opts?.method === 'POST')
        return Promise.reject(new ApiError(409, { detail: 'Transição inválida.' }))
      return Promise.resolve([req(), RESERVED])
    })
    render(<TransfusionRequestQueue canManage canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r2')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Liberar' }))
    await waitFor(() => expect(screen.getByText('Transição inválida.')).toBeInTheDocument())
  })

  it('opens the cancel modal', async () => {
    render(<TransfusionRequestQueue canManage canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())
    fireEvent.click(screen.getAllByRole('button', { name: 'Cancelar' })[0])
    expect(
      screen.getByRole('dialog', { name: 'Cancelar requisição transfusional' })
    ).toBeInTheDocument()
  })

  it('hides Nova requisição without hemoterapia.request', async () => {
    render(<TransfusionRequestQueue canManage canRequest={false} />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Nova requisição/ })).not.toBeInTheDocument()
  })

  it('opens the new-request modal with hemoterapia.request', async () => {
    render(<TransfusionRequestQueue canManage={false} canRequest />)
    await waitFor(() => expect(screen.getByLabelText('Requisição r1')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Nova requisição/ }))
    expect(
      screen.getByRole('dialog', { name: 'Nova requisição transfusional' })
    ).toBeInTheDocument()
  })

  it('shows an empty state when there are no requests', async () => {
    mockApiFetch.mockResolvedValue([])
    render(<TransfusionRequestQueue canManage={false} canRequest={false} />)
    await waitFor(() => expect(screen.getByText('Nenhuma requisição')).toBeInTheDocument())
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<TransfusionRequestQueue canManage={false} canRequest={false} />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar as requisições')).toBeInTheDocument()
    )
  })
})
