import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import RejeitarApacModal from './RejeitarApacModal'

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

describe('RejeitarApacModal', () => {
  it('disables confirm until a motivo is entered', () => {
    render(
      <RejeitarApacModal apacId={1} numeroAtual="2826" onClose={vi.fn()} onRejected={vi.fn()} />
    )
    const confirm = screen.getByRole('button', { name: 'Confirmar rejeição' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Motivo da rejeição'), {
      target: { value: 'Glosa administrativa' },
    })
    expect(confirm).toBeEnabled()
  })

  it('posts the motivo and notifies on success', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onRejected = vi.fn()
    render(
      <RejeitarApacModal apacId={1} numeroAtual="2826" onClose={vi.fn()} onRejected={onRejected} />
    )
    fireEvent.change(screen.getByLabelText('Motivo da rejeição'), {
      target: { value: 'Glosa administrativa' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar rejeição' }))

    await waitFor(() => expect(onRejected).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/billing/apac-autorizacoes/1/rejeitar/')
    expect(JSON.parse(opts!.body as string).motivo).toBe('Glosa administrativa')
  })
})
