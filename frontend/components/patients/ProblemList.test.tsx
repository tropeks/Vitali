import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ProblemList from './ProblemList'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

const PROBLEM_ACTIVE = {
  id: 'prob-1',
  patient: 'patient-1',
  condition: 'Diabetes mellitus tipo 2',
  cid10_code: 'E11',
  cid_unmatched: false,
  clinical_status: 'active',
  clinical_status_display: 'Ativo',
  verification_status: 'confirmed',
  verification_status_display: 'Confirmado',
  onset_date: '2022-03-10',
  abatement_date: null,
}

const PROBLEM_RESOLVED = {
  id: 'prob-2',
  patient: 'patient-1',
  condition: 'Pneumonia',
  cid10_code: 'J18',
  cid_unmatched: true,
  clinical_status: 'resolved',
  clinical_status_display: 'Resolvido',
  verification_status: 'confirmed',
  verification_status_display: 'Confirmado',
  onset_date: '2024-01-05',
  abatement_date: '2024-01-20',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ProblemList', () => {
  it('fetches the governed problem list scoped by patient', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ProblemList patientId="patient-1" />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/problems/?patient=patient-1')
    })
  })

  it('shows an empty state when there are no problems', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ProblemList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Sem problemas na lista')).toBeInTheDocument()
    })
  })

  it('renders governed problems with CID-10 and clinical status', async () => {
    mockApiFetch.mockResolvedValueOnce([PROBLEM_ACTIVE, PROBLEM_RESOLVED])
    render(<ProblemList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Diabetes mellitus tipo 2')).toBeInTheDocument()
    })
    expect(screen.getByText('Pneumonia')).toBeInTheDocument()
    expect(screen.getByText(/CID-10 E11/)).toBeInTheDocument()
    expect(screen.getByText(/CID-10 J18/)).toBeInTheDocument()
    expect(screen.getByText('Ativo')).toBeInTheDocument()
    expect(screen.getByText('Resolvido')).toBeInTheDocument()
    // Unmatched governed CID is flagged.
    expect(screen.getByText('não reconciliado')).toBeInTheDocument()
  })

  it('handles the paginated {results,count} envelope', async () => {
    mockApiFetch.mockResolvedValueOnce({ count: 1, results: [PROBLEM_ACTIVE] })
    render(<ProblemList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Diabetes mellitus tipo 2')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<ProblemList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar problemas')).toBeInTheDocument()
    })
  })
})
