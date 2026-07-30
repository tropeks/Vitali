import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import MicrobiologyPanel from './MicrobiologyPanel'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

const mockApiFetch = vi.mocked(apiFetch)

const RESULTS = {
  results: [
    {
      id: 'm1',
      order_item: 'oi1',
      culture_result: 'positiva',
      specimen: 'Urocultura',
      gram_stain: 'Bacilos Gram-negativos',
      organisms: [
        {
          id: 'o1',
          result: 'm1',
          organism_name: 'Escherichia coli',
          colony_count: '>100.000 UFC/mL',
          is_significant: true,
          antibiogram: [
            { id: 'a1', organism: 'o1', antibiotic: 'Ciprofloxacino', interpretation: 'S' },
            { id: 'a2', organism: 'o1', antibiotic: 'Ampicilina', interpretation: 'R' },
          ],
        },
      ],
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MicrobiologyPanel', () => {
  it('renders culture, organism and antibiogram S/R badges', async () => {
    mockApiFetch.mockResolvedValueOnce(RESULTS)
    render(<MicrobiologyPanel patientId="p1" canRead />)

    await waitFor(() => expect(screen.getByText('Escherichia coli')).toBeInTheDocument())
    expect(screen.getByText('Positiva')).toBeInTheDocument()
    expect(screen.getByText('Ciprofloxacino')).toBeInTheDocument()
    expect(screen.getByText('Ampicilina')).toBeInTheDocument()
    expect(screen.getByText('S')).toBeInTheDocument()
    expect(screen.getByText('R')).toBeInTheDocument()
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/microbiology-results/?patient=p1')
  })

  it('shows an empty state when there are no results', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: [] })
    render(<MicrobiologyPanel patientId="p1" canRead />)
    await waitFor(() =>
      expect(screen.getByText('Nenhum resultado de microbiologia')).toBeInTheDocument()
    )
  })

  it('shows a permission notice without emr.read (and does not fetch)', () => {
    render(<MicrobiologyPanel patientId="p1" canRead={false} />)
    expect(screen.getByText('Sem acesso à microbiologia')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<MicrobiologyPanel patientId="p1" canRead />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar microbiologia')).toBeInTheDocument()
    )
  })
})
