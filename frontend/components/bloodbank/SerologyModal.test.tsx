import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import SerologyModal from './SerologyModal'

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

describe('SerologyModal', () => {
  it('posts all seven RDC 34 markers and reports the release outcome', async () => {
    mockApiFetch.mockResolvedValue({ id: 's1', all_non_reactive: true })
    const onDone = vi.fn()
    render(
      <SerologyModal bagId="b1" bagIdentifier="DIN-001" onClose={() => {}} onDone={onDone} />
    )

    // Defaults are all "nao_reagente" → will release
    expect(screen.getByText(/será LIBERADA/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Registrar sorologia' }))

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(true))
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/blood-bag-serologies/')
    const body = JSON.parse((opts as any).body)
    expect(body.bag).toBe('b1')
    expect(body.hiv).toBe('nao_reagente')
    expect(body.htlv).toBe('nao_reagente')
  })

  it('warns the bag will be discarded when a marker is reagente', async () => {
    mockApiFetch.mockResolvedValue({ id: 's2', all_non_reactive: false })
    const onDone = vi.fn()
    render(
      <SerologyModal bagId="b1" bagIdentifier="DIN-001" onClose={() => {}} onDone={onDone} />
    )

    fireEvent.change(screen.getByLabelText('HIV'), { target: { value: 'reagente' } })
    expect(screen.getByText(/será DESCARTADA/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Registrar sorologia' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(false))
    const body = JSON.parse((mockApiFetch.mock.calls[0][1] as any).body)
    expect(body.hiv).toBe('reagente')
  })

  it('surfaces a 409 (bag not in quarantine) as a friendly message', async () => {
    const { ApiError } = await import('@/lib/api')
    mockApiFetch.mockRejectedValue(new ApiError(409, { detail: 'Bolsa não está em quarentena.' }))
    const onDone = vi.fn()
    render(
      <SerologyModal bagId="b1" bagIdentifier="DIN-001" onClose={() => {}} onDone={onDone} />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Registrar sorologia' }))
    await waitFor(() =>
      expect(screen.getByText('Bolsa não está em quarentena.')).toBeInTheDocument()
    )
    expect(onDone).not.toHaveBeenCalled()
  })
})
