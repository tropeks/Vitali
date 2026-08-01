import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import LabEspecializadoTab from './LabEspecializadoTab'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn((url: string) => {
    if (url.startsWith('/api/v1/lab-orders/')) {
      return Promise.resolve([
        {
          id: 'o1',
          items: [
            { id: 'it1', test_name: 'Urocultura', category: 'microbiology' },
            { id: 'it2', test_name: 'Anatomopatológico mama', category: 'pathology' },
          ],
        },
      ])
    }
    // micro-results / pathology-reports panels
    return Promise.resolve({ results: [] })
  }),
  ApiError: class ApiError extends Error {},
}))

const mockApiFetch = vi.mocked(apiFetch)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LabEspecializadoTab', () => {
  it('offers the pending lab orders to launch when the user has emr.write', async () => {
    render(<LabEspecializadoTab patientId="p1" canRead canWrite />)
    await waitFor(() =>
      expect(screen.getByLabelText('Novo resultado de microbiologia')).toBeInTheDocument(),
    )
    // The micro picker lists the microbiology order; the AP picker the pathology one.
    expect(screen.getByRole('option', { name: 'Urocultura' })).toBeInTheDocument()
    expect(screen.getByLabelText('Novo laudo anatomopatológico')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Anatomopatológico mama' })).toBeInTheDocument()
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/lab-orders/?patient=p1')
  })

  it('hides the launch pickers without emr.write', async () => {
    render(<LabEspecializadoTab patientId="p1" canRead canWrite={false} />)
    // panels still render (read), but no launch pickers
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    expect(screen.queryByLabelText('Novo resultado de microbiologia')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Novo laudo anatomopatológico')).not.toBeInTheDocument()
  })
})
