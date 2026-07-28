import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SaeCareplan from './SaeCareplan'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

// Prescription child self-fetches; keep it quiet with an empty list.
const CAREPLAN = {
  id: 'plan-1',
  diagnosis: 'diag-1',
  noc: 7,
  noc_code: '2102',
  noc_unmatched: false,
  expected_outcome: 'Controle da dor',
  target: 'Escala de dor <= 3 em 48h',
  created_at: '2026-07-20T10:00:00Z',
}

const INTERVENTION = {
  id: 'int-1',
  careplan: 'plan-1',
  nic: 11,
  nic_code: '1400',
  nic_unmatched: false,
  notes: 'Controle da dor: administrar analgesia prescrita',
  created_at: '2026-07-20T10:05:00Z',
}

function routeApi(overrides: Record<string, any> = {}) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/nursing-careplans/')) {
      return Promise.resolve(overrides.careplans ?? [])
    }
    if (url.startsWith('/api/v1/nursing-care-interventions/')) {
      return Promise.resolve(overrides.interventions ?? [])
    }
    if (url.startsWith('/api/v1/nursing-prescription-items/')) {
      return Promise.resolve([])
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SaeCareplan', () => {
  it('fetches careplans scoped by diagnosis', async () => {
    routeApi({ careplans: [] })
    render(<SaeCareplan diagnosisId="diag-1" canWrite={false} />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/nursing-careplans/?diagnosis=diag-1')
    })
  })

  it('shows an empty state when there is no plan', async () => {
    routeApi({ careplans: [] })
    render(<SaeCareplan diagnosisId="diag-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Sem plano de cuidados')).toBeInTheDocument()
    })
  })

  it('renders the NOC outcome/target and NIC interventions', async () => {
    routeApi({ careplans: [CAREPLAN], interventions: [INTERVENTION] })
    render(<SaeCareplan diagnosisId="diag-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Controle da dor')).toBeInTheDocument()
    })
    expect(screen.getByText(/Escala de dor <= 3 em 48h/)).toBeInTheDocument()
    expect(screen.getByText(/2102/)).toBeInTheDocument()
    // Interventions are loaded by a self-fetching child (separate effect), so
    // await their async render rather than asserting synchronously (race).
    await waitFor(() => {
      expect(
        screen.getByText('Controle da dor: administrar analgesia prescrita')
      ).toBeInTheDocument()
    })
    expect(screen.getByText(/1400/)).toBeInTheDocument()
  })
})
