import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import ReleaseBedModal from './ReleaseBedModal'

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

describe('ReleaseBedModal', () => {
  it('posts the release to the bed endpoint and notifies on success', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onReleased = vi.fn()
    render(
      <ReleaseBedModal
        bedId="b3"
        bedIdentifier="UTI-03"
        onClose={vi.fn()}
        onReleased={onReleased}
      />
    )

    fireEvent.change(screen.getByLabelText('Motivo da liberação'), {
      target: { value: 'Limpeza terminal concluída' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar liberação' }))

    await waitFor(() => expect(onReleased).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/beds/b3/release/')
    expect(opts?.method).toBe('POST')
    expect(JSON.parse(opts!.body as string).reason).toBe('Limpeza terminal concluída')
  })

  it('omits reason from the body when left blank', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    render(
      <ReleaseBedModal bedId="b3" bedIdentifier="UTI-03" onClose={vi.fn()} onReleased={vi.fn()} />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar liberação' }))
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [, opts] = mockApiFetch.mock.calls[0]
    expect(JSON.parse(opts!.body as string)).toEqual({})
  })

  it('surfaces a friendly message on 409 (bed not em higienização)', async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(409, { detail: 'x' }))
    const onReleased = vi.fn()
    render(
      <ReleaseBedModal bedId="b3" bedIdentifier="UTI-03" onClose={vi.fn()} onReleased={onReleased} />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar liberação' }))
    await waitFor(() =>
      expect(screen.getByText(/não está em higienização/i)).toBeInTheDocument()
    )
    expect(onReleased).not.toHaveBeenCalled()
  })
})
