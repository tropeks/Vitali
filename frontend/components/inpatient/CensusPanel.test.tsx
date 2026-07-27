import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import CensusPanel from './CensusPanel'

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

const CENSUS = {
  occupancy: [
    {
      unit: { id: 'u1', code: 'UTI', name: 'UTI Adulto' },
      total_beds: 4,
      status_counts: {
        ocupado: 3,
        livre: 1,
        higienizacao: 0,
        bloqueado: 0,
        reservado: 0,
        interditado: 0,
      },
      operational_beds: 4,
      occupied: 3,
      occupancy_rate: 0.75,
    },
  ],
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

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CensusPanel', () => {
  it('fetches the census endpoint', async () => {
    mockApiFetch.mockResolvedValue(CENSUS)
    render(<CensusPanel />)
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/admissions/census/')
    )
  })

  it('shows the occupancy rate as a percent and counts by status', async () => {
    mockApiFetch.mockResolvedValue(CENSUS)
    render(<CensusPanel />)
    await waitFor(() => expect(screen.getByText('75%')).toBeInTheDocument())
    // KPI label combines name + code
    expect(screen.getByText('UTI Adulto · UTI')).toBeInTheDocument()
    expect(screen.getByText(/3\/4 operacionais/)).toBeInTheDocument()
    expect(screen.getByText(/Ocupado: 3/)).toBeInTheDocument()
    expect(screen.getByText(/Livre: 1/)).toBeInTheDocument()
  })

  it('lists internados with bed, unit and LOS (formatted + raw hours)', async () => {
    mockApiFetch.mockResolvedValue(CENSUS)
    render(<CensusPanel />)
    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    expect(screen.getByText('UTI-01')).toBeInTheDocument()
    // 30h formatted coarse = "1d 6h"; raw hours also shown
    expect(screen.getByText(/1d 6h/)).toBeInTheDocument()
    expect(screen.getByText(/\(30h\)/)).toBeInTheDocument()
  })

  it('shows an empty state when nobody is internado', async () => {
    mockApiFetch.mockResolvedValue({ occupancy: [], census: [] })
    render(<CensusPanel />)
    await waitFor(() =>
      expect(screen.getByText('Nenhum paciente internado')).toBeInTheDocument()
    )
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<CensusPanel />)
    await waitFor(() => expect(screen.getByText('Erro ao carregar o censo')).toBeInTheDocument())
  })
})
