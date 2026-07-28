import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import OpenBoletimModal from './OpenBoletimModal'

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
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/patients/')) {
      return Promise.resolve({ results: [{ id: 'p1', full_name: 'Maria Silva' }], next: null })
    }
    return Promise.resolve({ id: 'new-boletim' })
  })
})

describe('OpenBoletimModal', () => {
  it('posts a new boletim with the chosen patient, mode and queixa', async () => {
    const onOpened = vi.fn()
    render(<OpenBoletimModal onClose={vi.fn()} onOpened={onOpened} />)

    // Pick the patient via the combobox.
    fireEvent.focus(screen.getByRole('combobox', { name: 'Paciente' }))
    fireEvent.click(await screen.findByRole('option', { name: 'Maria Silva' }))

    // Choose meio de chegada + queixa.
    fireEvent.change(screen.getByLabelText('Meio de chegada'), { target: { value: 'ambulancia' } })
    fireEvent.change(screen.getByLabelText('Queixa principal'), {
      target: { value: 'Dor torácica' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Abrir boletim' }))

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    const call = mockApiFetch.mock.calls.find(([u]) => u === '/api/v1/emergency-encounters/')!
    expect(JSON.parse((call[1] as any).body)).toEqual({
      patient: 'p1',
      mode_of_arrival: 'ambulancia',
      chief_complaint: 'Dor torácica',
    })
    expect(onOpened).toHaveBeenCalled()
  })

  it('requires a patient before posting', async () => {
    render(<OpenBoletimModal onClose={vi.fn()} onOpened={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Abrir boletim' }))
    expect(await screen.findByText('Selecione o paciente.')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalledWith(
      '/api/v1/emergency-encounters/',
      expect.anything(),
    )
  })
})
