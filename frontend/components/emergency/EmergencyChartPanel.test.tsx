import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import EmergencyChartPanel from './EmergencyChartPanel'

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

const CLASSIFICATION = {
  id: 'rc-1',
  boletim: 'bol-1',
  flowchart: 'fc-1',
  flowchart_code: 'DOR-TORAX',
  discriminator: 'disc-1',
  discriminator_code: 'DOR-PRECORDIAL',
  acuity_level: 'laranja',
  target_minutes: 10,
  classified_at: '2026-07-25T13:00:00Z',
  notes: '',
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
  current_classification: CLASSIFICATION,
}

function routeApi(overrides: { boletins?: any } = {}) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/emergency-encounters/?patient=')) {
      return Promise.resolve(overrides.boletins ?? [BOLETIM])
    }
    if (url.startsWith('/api/v1/emergency-encounters/bol-1/')) {
      return Promise.resolve(BOLETIM)
    }
    if (url.startsWith('/api/v1/risk-classifications/?boletim=')) {
      return Promise.resolve([CLASSIFICATION])
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('EmergencyChartPanel', () => {
  it('hides everything without emergency.read', () => {
    routeApi()
    render(
      <EmergencyChartPanel patientId="patient-1" canRead={false} canClassify canManage />,
    )
    expect(screen.getByText('Sem acesso à emergência')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('fetches the patient boletins with emergency.read', async () => {
    routeApi()
    render(
      <EmergencyChartPanel patientId="patient-1" canRead canClassify={false} canManage={false} />,
    )
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/?patient=patient-1',
      )
    })
  })

  it('lists boletins with status, arrival and current acuity', async () => {
    routeApi()
    render(<EmergencyChartPanel patientId="patient-1" canRead canClassify canManage />)
    await waitFor(() => {
      expect(screen.getByText('Classificado')).toBeInTheDocument()
    })
    // Acuity badge from the ACUITY_META map (current_classification).
    expect(screen.getByText('Laranja (muito urgente)')).toBeInTheDocument()
    // Target minutes copied from the classification.
    expect(screen.getByText(/Tempo-alvo 10 min/)).toBeInTheDocument()
    // Chief complaint + mode of arrival label.
    expect(screen.getByText('Dor no peito')).toBeInTheDocument()
    expect(screen.getByText(/Ambulância/)).toBeInTheDocument()
  })

  it('shows an empty state with no boletins', async () => {
    routeApi({ boletins: [] })
    render(<EmergencyChartPanel patientId="patient-1" canRead canClassify canManage />)
    await waitFor(() => {
      expect(screen.getByText('Sem boletim de emergência')).toBeInTheDocument()
    })
  })

  it('opens the case detail when a boletim is selected', async () => {
    routeApi()
    render(<EmergencyChartPanel patientId="patient-1" canRead canClassify canManage />)
    await waitFor(() => {
      expect(screen.getByText('Dor no peito')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Dor no peito/ }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/emergency-encounters/bol-1/')
    })
    expect(screen.getByText('Atendimento de emergência')).toBeInTheDocument()
  })
})
