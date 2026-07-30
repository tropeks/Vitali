import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import PlannedDischargesPanel from './PlannedDischargesPanel'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

const mockApiFetch = vi.mocked(apiFetch)

const PLANNED = {
  planned: [
    {
      admission_id: 'a1',
      patient: { id: 'p1', name: 'Maria Silva' },
      current_bed: { id: 'b1', identifier: 'UTI-01' },
      unit_id: 'u1',
      expected_discharge_datetime: '2026-07-10T14:30:00Z',
    },
    {
      admission_id: 'a2',
      patient: { id: 'p2', name: 'João Souza' },
      current_bed: null,
      unit_id: null,
      expected_discharge_datetime: '2026-07-12T09:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PlannedDischargesPanel', () => {
  it('lists planned discharges with patient, bed and formatted datetime', async () => {
    mockApiFetch.mockResolvedValueOnce(PLANNED)
    render(<PlannedDischargesPanel />)

    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    expect(screen.getByText('João Souza')).toBeInTheDocument()
    expect(screen.getByText('UTI-01')).toBeInTheDocument()
    // Null bed renders as em-dash placeholder.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
    // Hits the planned endpoint.
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/admissions/planned/')
  })

  it('shows an empty state when there are no planned discharges', async () => {
    mockApiFetch.mockResolvedValueOnce({ planned: [] })
    render(<PlannedDischargesPanel />)
    await waitFor(() =>
      expect(screen.getByText('Nenhuma alta prevista')).toBeInTheDocument()
    )
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<PlannedDischargesPanel />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar altas previstas')).toBeInTheDocument()
    )
  })
})
