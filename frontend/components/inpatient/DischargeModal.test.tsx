import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import DischargeModal from './DischargeModal'

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

describe('DischargeModal', () => {
  it('posts the discharge with the chosen disposition', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onDischarged = vi.fn()
    render(
      <DischargeModal
        admissionId="a1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onDischarged={onDischarged}
      />
    )

    fireEvent.change(screen.getByLabelText('Desfecho da alta'), {
      target: { value: 'transferencia_externa' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar alta' }))

    await waitFor(() => expect(onDischarged).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/admissions/a1/discharge/')
    expect(opts?.method).toBe('POST')
    expect(JSON.parse(opts!.body as string).disposition).toBe('transferencia_externa')
  })

  it('defaults the disposition to alta_melhorada', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    render(
      <DischargeModal
        admissionId="a1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onDischarged={vi.fn()}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar alta' }))
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    expect(JSON.parse(mockApiFetch.mock.calls[0][1]!.body as string).disposition).toBe(
      'alta_melhorada'
    )
  })

  it('surfaces a 409 conflict with a friendly message', async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(409, { detail: 'encerrada' }))
    const onDischarged = vi.fn()
    render(
      <DischargeModal
        admissionId="a1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onDischarged={onDischarged}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar alta' }))
    await waitFor(() =>
      expect(screen.getByText(/já foi encerrada/)).toBeInTheDocument()
    )
    expect(onDischarged).not.toHaveBeenCalled()
  })
})
