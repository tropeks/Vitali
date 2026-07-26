import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ImmunizationList from './ImmunizationList'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

const SHOT = {
  id: 'imm-1',
  patient: 'patient-1',
  immunobiological: 'Tríplice viral (SCR)',
  dose_number: '1ª dose',
  lot: 'LOTE-9988',
  manufacturer: 'Fiocruz',
  date: '2025-02-14',
  pni_calendar_reference: 'PNI 12 meses',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ImmunizationList', () => {
  it('fetches immunizations scoped by patient', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ImmunizationList patientId="patient-1" />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/immunizations/?patient=patient-1')
    })
  })

  it('shows an empty state when there are no records', async () => {
    mockApiFetch.mockResolvedValueOnce([])
    render(<ImmunizationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Sem registro vacinal')).toBeInTheDocument()
    })
  })

  it('renders vaccine records with dose, lot and PNI reference', async () => {
    mockApiFetch.mockResolvedValueOnce([SHOT])
    render(<ImmunizationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Tríplice viral (SCR)')).toBeInTheDocument()
    })
    expect(screen.getByText('1ª dose')).toBeInTheDocument()
    expect(screen.getByText(/LOTE-9988/)).toBeInTheDocument()
    expect(screen.getByText(/PNI 12 meses/)).toBeInTheDocument()
  })

  it('handles the paginated {results,count} envelope', async () => {
    mockApiFetch.mockResolvedValueOnce({ count: 1, results: [SHOT] })
    render(<ImmunizationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Tríplice viral (SCR)')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<ImmunizationList patientId="patient-1" />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar imunizações')).toBeInTheDocument()
    })
  })
})
