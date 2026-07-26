import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ReconciliationList from './ReconciliationList'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

const RECONCILIATION = {
  id: 'rec-1',
  patient: 'patient-1',
  encounter: 'enc-1',
  moment: 'admission',
  moment_display: 'Admissão',
  status: 'completed',
  status_display: 'Concluída',
  author: 'user-1',
  notes: '',
  completed_at: '2026-05-07T11:00:00Z',
  created_at: '2026-05-07T10:00:00Z',
  items: [
    {
      id: 'item-1',
      medication_name: 'Losartana 50mg',
      home_dosage: '1x ao dia',
      action: 'continue',
      action_display: 'Manter',
      reason: 'Controle pressórico estável',
    },
    {
      id: 'item-2',
      medication_name: 'AAS 100mg',
      home_dosage: '1x ao dia',
      action: 'stop',
      action_display: 'Suspender',
      reason: 'Risco de sangramento',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ReconciliationList', () => {
  it('fetches reconciliations scoped by patient', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ReconciliationList patientId="patient-1" />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/medication-reconciliations/?patient=patient-1')
    })
  })

  it('shows an empty state when there are no reconciliations', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ReconciliationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Sem reconciliação medicamentosa')).toBeInTheDocument()
    })
  })

  it('renders transitions, status and per-medication decisions', async () => {
    mockApiFetch.mockResolvedValueOnce([RECONCILIATION])
    render(<ReconciliationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText(/Admissão/)).toBeInTheDocument()
    })
    expect(screen.getByText('Concluída')).toBeInTheDocument()
    expect(screen.getByText('Losartana 50mg')).toBeInTheDocument()
    expect(screen.getByText('AAS 100mg')).toBeInTheDocument()
    expect(screen.getByText('Manter')).toBeInTheDocument()
    expect(screen.getByText('Suspender')).toBeInTheDocument()
    expect(screen.getByText(/Risco de sangramento/)).toBeInTheDocument()
  })

  it('handles the paginated {results,count} envelope', async () => {
    mockApiFetch.mockResolvedValueOnce({ count: 1, results: [RECONCILIATION] })
    render(<ReconciliationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Losartana 50mg')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<ReconciliationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar reconciliações')).toBeInTheDocument()
    })
  })
})
