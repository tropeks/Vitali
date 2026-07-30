import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import PathologyPanel from './PathologyPanel'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

const mockApiFetch = vi.mocked(apiFetch)

const REPORTS = {
  results: [
    {
      id: 'r1',
      order_item: 'oi2',
      report_number: 'AP-2026-0001',
      clinical_history: 'Nódulo mamário suspeito',
      diagnosis: 'Carcinoma ductal invasivo',
      macroscopy: 'Fragmento pardo',
      cid_o_topography: 'C50.9',
      cid_o_morphology: '8500/3',
      status: 'final',
      reported_at: '2026-07-05T10:00:00Z',
      specimens: [
        { id: 's1', report: 'r1', label: 'A', site: 'Mama esquerda', blocks_count: 3 },
      ],
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PathologyPanel', () => {
  it('renders report status, diagnosis, CID-O and specimens', async () => {
    mockApiFetch.mockResolvedValueOnce(REPORTS)
    render(<PathologyPanel patientId="p1" canRead />)

    await waitFor(() => expect(screen.getByText('AP-2026-0001')).toBeInTheDocument())
    expect(screen.getByText('Final')).toBeInTheDocument()
    expect(screen.getByText('Carcinoma ductal invasivo')).toBeInTheDocument()
    expect(screen.getByText('C50.9')).toBeInTheDocument()
    expect(screen.getByText('8500/3')).toBeInTheDocument()
    expect(screen.getByText(/Mama esquerda/)).toBeInTheDocument()
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/pathology-reports/?patient=p1')
  })

  it('shows an empty state when there are no reports', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: [] })
    render(<PathologyPanel patientId="p1" canRead />)
    await waitFor(() =>
      expect(screen.getByText('Nenhum laudo anatomopatológico')).toBeInTheDocument()
    )
  })

  it('shows a permission notice without emr.read (and does not fetch)', () => {
    render(<PathologyPanel patientId="p1" canRead={false} />)
    expect(screen.getByText('Sem acesso à anatomia patológica')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })
})
