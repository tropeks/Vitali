import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import SurgicalCancelModal from './SurgicalCancelModal'

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

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SurgicalCancelModal', () => {
  it('posts the cancel with the given reason', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onCancelled = vi.fn()
    render(
      <SurgicalCancelModal
        caseId="c1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onCancelled={onCancelled}
      />
    )
    fireEvent.change(screen.getByLabelText('Motivo do cancelamento'), {
      target: { value: 'Sem condições clínicas' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar cirurgia' }))

    await waitFor(() => expect(onCancelled).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/surgical-cases/c1/cancel/')
    expect((opts as any)?.method).toBe('POST')
    expect(JSON.parse((opts as any).body).reason).toBe('Sem condições clínicas')
  })

  it('surfaces an illegal-transition 409 inline', async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(409, { detail: 'ilegal' }))
    const onCancelled = vi.fn()
    render(
      <SurgicalCancelModal
        caseId="c1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onCancelled={onCancelled}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar cirurgia' }))
    await waitFor(() =>
      expect(screen.getByText(/Não é possível cancelar este caso/)).toBeInTheDocument()
    )
    expect(onCancelled).not.toHaveBeenCalled()
  })
})
