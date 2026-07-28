import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import DispositionModal from './DispositionModal'

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

function routeApi(closeImpl?: () => Promise<any>) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/beds/')) {
      return Promise.resolve([{ id: 'bed1', identifier: 'UTI-01' }])
    }
    if (url.startsWith('/api/v1/professionals/')) {
      return Promise.resolve({ results: [{ id: 'prof1', user_name: 'Dr. House' }], next: null })
    }
    if (url.includes('/close/')) {
      return closeImpl ? closeImpl() : Promise.resolve({ id: 'b1' })
    }
    return Promise.resolve({})
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DispositionModal', () => {
  it('posts a simple alta desfecho', async () => {
    routeApi()
    const onClosed = vi.fn()
    render(
      <DispositionModal boletimId="b1" patientName="Maria" onClose={vi.fn()} onClosed={onClosed} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar desfecho' }))

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/b1/close/',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    const call = mockApiFetch.mock.calls.find(([u]) => u === '/api/v1/emergency-encounters/b1/close/')!
    expect(JSON.parse((call[1] as any).body)).toEqual({ disposition: 'alta' })
    expect(onClosed).toHaveBeenCalled()
  })

  it('surfaces a friendly error on a 409 (leito ocupado / transição inválida)', async () => {
    routeApi(() => Promise.reject(new ApiError(409, { detail: 'ocupado' })))
    render(<DispositionModal boletimId="b1" patientName="Maria" onClose={vi.fn()} onClosed={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar desfecho' }))
    await waitFor(() =>
      expect(
        screen.getByText(/Leito ocupado ou transição inválida/),
      ).toBeInTheDocument(),
    )
  })

  it('loads free beds on internação and posts bed + professionals', async () => {
    routeApi()
    render(<DispositionModal boletimId="b1" patientName="Maria" onClose={vi.fn()} onClosed={vi.fn()} />)

    // Switch to internação → free beds load.
    fireEvent.change(screen.getByLabelText('Desfecho'), { target: { value: 'internacao' } })
    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/beds/?status=livre'))

    // Choose a leito → the professional pickers appear.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'UTI-01' })).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText('Leito livre'), { target: { value: 'bed1' } })

    // Fill both professionals.
    fireEvent.focus(screen.getByRole('combobox', { name: 'Profissional internador' }))
    fireEvent.click((await screen.findAllByRole('option', { name: 'Dr. House' }))[0])
    fireEvent.focus(screen.getByRole('combobox', { name: 'Profissional responsável' }))
    fireEvent.click((await screen.findAllByRole('option', { name: 'Dr. House' }))[0])

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar desfecho' }))

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/b1/close/',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    const call = mockApiFetch.mock.calls.find(([u]) => u === '/api/v1/emergency-encounters/b1/close/')!
    expect(JSON.parse((call[1] as any).body)).toEqual({
      disposition: 'internacao',
      bed: 'bed1',
      admission_source: 'emergencia',
      admitting_professional: 'prof1',
      attending_professional: 'prof1',
    })
  })

  it('blocks internação with a bed but no professionals', async () => {
    routeApi()
    render(<DispositionModal boletimId="b1" patientName="Maria" onClose={vi.fn()} onClosed={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Desfecho'), { target: { value: 'internacao' } })
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'UTI-01' })).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText('Leito livre'), { target: { value: 'bed1' } })

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar desfecho' }))
    expect(
      await screen.findByText(/selecione profissional internador e responsável/i),
    ).toBeInTheDocument()
  })
})
