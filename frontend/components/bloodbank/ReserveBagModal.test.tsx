import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import ReserveBagModal from './ReserveBagModal'
import type { TransfusionRequestDTO } from './bloodbank-types'

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

const REQUEST: TransfusionRequestDTO = {
  id: 'r1',
  patient: 'p1',
  component: 7,
  component_display: 'Concentrado de Hemácias',
  quantidade: 2,
  indicacao: 'Anemia',
  urgencia: 'rotina',
  requester: 'prof1',
  status: 'solicitada',
  crossmatches: [],
}

const AVAILABLE = [
  {
    id: 'bag-1',
    identifier: 'DIN-100',
    component: 7,
    abo: 'O',
    rh_factor: 'positivo',
    volume_ml: 300,
    collection_date: '2026-07-01',
    expiry_date: '2026-12-31',
    serology_status: 'liberada',
    stock_status: 'disponivel',
    irradiada: false,
    leucodepletada: false,
    aferese: false,
    available: true,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReserveBagModal', () => {
  it('lists available bags of the requested component and reserves the chosen one', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.startsWith('/api/v1/blood-bags/')) return Promise.resolve(AVAILABLE)
      if (url.includes('/reservar/') && opts?.method === 'POST') return Promise.resolve({})
      return Promise.resolve({})
    })
    const onReserved = vi.fn()
    render(<ReserveBagModal request={REQUEST} onClose={() => {}} onReserved={onReserved} />)

    await waitFor(() => expect(screen.getByText('DIN-100')).toBeInTheDocument())
    // fetched available bags for the component
    expect(
      mockApiFetch.mock.calls.some(([u]) =>
        (u as string).includes('/blood-bags/?available=true&component=7')
      )
    ).toBe(true)

    fireEvent.click(screen.getByRole('radio'))
    fireEvent.click(screen.getByRole('button', { name: 'Reservar bolsa' }))

    await waitFor(() => expect(onReserved).toHaveBeenCalled())
    const call = mockApiFetch.mock.calls.find(([u]) =>
      (u as string).includes('/transfusion-requests/r1/reservar/')
    )
    expect(call).toBeTruthy()
    expect(JSON.parse((call![1] as any).body)).toEqual({ bag: 'bag-1' })
  })

  it('surfaces a 409 (incompatible/unavailable bag) as a friendly message', async () => {
    const { ApiError } = await import('@/lib/api')
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.startsWith('/api/v1/blood-bags/')) return Promise.resolve(AVAILABLE)
      if (url.includes('/reservar/') && opts?.method === 'POST')
        return Promise.reject(new ApiError(409, { detail: 'Bolsa incompatível.' }))
      return Promise.resolve({})
    })
    const onReserved = vi.fn()
    render(<ReserveBagModal request={REQUEST} onClose={() => {}} onReserved={onReserved} />)

    await waitFor(() => expect(screen.getByText('DIN-100')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('radio'))
    fireEvent.click(screen.getByRole('button', { name: 'Reservar bolsa' }))

    await waitFor(() => expect(screen.getByText('Bolsa incompatível.')).toBeInTheDocument())
    expect(onReserved).not.toHaveBeenCalled()
  })

  it('shows an empty state when no compatible bag is available', async () => {
    mockApiFetch.mockResolvedValue([])
    render(<ReserveBagModal request={REQUEST} onClose={() => {}} onReserved={() => {}} />)
    await waitFor(() =>
      expect(screen.getByText('Nenhuma bolsa disponível')).toBeInTheDocument()
    )
  })
})
