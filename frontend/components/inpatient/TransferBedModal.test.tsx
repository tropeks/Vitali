import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import TransferBedModal from './TransferBedModal'
import type { BoardBed } from './inpatient-types'

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

const FREE_BEDS: BoardBed[] = [
  { id: 'b2', identifier: 'UTI-02', status: 'livre', patient: null },
  { id: 'b3', identifier: 'UTI-03', status: 'livre', patient: null },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TransferBedModal', () => {
  it('posts the transfer with the chosen destination bed', async () => {
    mockApiFetch.mockResolvedValueOnce({})
    const onTransferred = vi.fn()
    render(
      <TransferBedModal
        admissionId="a1"
        patientName="Maria Silva"
        freeBeds={FREE_BEDS}
        onClose={vi.fn()}
        onTransferred={onTransferred}
      />
    )

    fireEvent.change(screen.getByLabelText('Leito de destino'), { target: { value: 'b3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Transferir' }))

    await waitFor(() => expect(onTransferred).toHaveBeenCalled())
    const [url, opts] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/admissions/a1/transfer/')
    expect(opts?.method).toBe('POST')
    expect(JSON.parse(opts!.body as string).to_bed).toBe('b3')
  })

  it('surfaces a 409 as a friendly "leito ocupado" message', async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(409, { detail: 'ocupado' }))
    const onTransferred = vi.fn()
    render(
      <TransferBedModal
        admissionId="a1"
        patientName="Maria Silva"
        freeBeds={FREE_BEDS}
        onClose={vi.fn()}
        onTransferred={onTransferred}
      />
    )

    fireEvent.change(screen.getByLabelText('Leito de destino'), { target: { value: 'b2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Transferir' }))

    await waitFor(() =>
      expect(screen.getByText(/Leito ocupado/)).toBeInTheDocument()
    )
    expect(onTransferred).not.toHaveBeenCalled()
  })

  it('keeps the submit disabled until a destination is picked', () => {
    render(
      <TransferBedModal
        admissionId="a1"
        patientName="Maria Silva"
        freeBeds={FREE_BEDS}
        onClose={vi.fn()}
        onTransferred={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: 'Transferir' })).toBeDisabled()
  })
})
