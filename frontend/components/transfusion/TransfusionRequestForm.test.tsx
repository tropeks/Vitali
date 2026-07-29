import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import TransfusionRequestForm from './TransfusionRequestForm'

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

const COMPONENTS = [
  { id: 1, code: 'CH', display: 'Concentrado de hemácias' },
  { id: 2, code: 'PFC', display: 'Plasma fresco congelado' },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TransfusionRequestForm', () => {
  it('loads the hemocomponente catalog and POSTs the requisição tied to the active encounter', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url === '/api/v1/blood-components/') return Promise.resolve(COMPONENTS)
      return Promise.resolve({ id: 'req-1', status: 'solicitada' })
    })
    const onCreated = vi.fn()
    render(
      <TransfusionRequestForm
        patientId="patient-1"
        encounterId="enc-1"
        onClose={vi.fn()}
        onCreated={onCreated}
      />,
    )

    // Catalog options render once loaded.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Concentrado de hemácias/ })).toBeInTheDocument(),
    )

    fireEvent.change(screen.getByLabelText('Hemocomponente'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Quantidade'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Urgência'), { target: { value: 'urgencia' } })
    fireEvent.change(screen.getByLabelText('Indicação clínica'), {
      target: { value: 'Anemia sintomática, Hb 6.5' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Solicitar' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    const postCall = mockApiFetch.mock.calls.find(
      ([url]) => url === '/api/v1/transfusion-requests/',
    )
    expect(postCall).toBeDefined()
    const body = JSON.parse((postCall![1] as RequestInit)?.body as string)
    expect(body).toEqual({
      patient: 'patient-1',
      component: 1,
      quantidade: 2,
      urgencia: 'urgencia',
      indicacao: 'Anemia sintomática, Hb 6.5',
      encounter: 'enc-1',
    })
  })

  it('surfaces backend field validation errors (400) inline', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url === '/api/v1/blood-components/') return Promise.resolve(COMPONENTS)
      return Promise.reject(
        new ApiError(400, { quantidade: ['Estoque insuficiente para a quantidade solicitada.'] }),
      )
    })
    render(
      <TransfusionRequestForm
        patientId="patient-1"
        encounterId="enc-1"
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    )

    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Concentrado de hemácias/ })).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText('Hemocomponente'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Indicação clínica'), {
      target: { value: 'Anemia' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Solicitar' }))

    await waitFor(() =>
      expect(
        screen.getByText('Estoque insuficiente para a quantidade solicitada.'),
      ).toBeInTheDocument(),
    )
  })

  it('warns when there is no active encounter to tie the requisição to', () => {
    mockApiFetch.mockResolvedValue(COMPONENTS)
    render(
      <TransfusionRequestForm
        patientId="patient-1"
        encounterId={null}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />,
    )
    expect(screen.getByText(/precisa de um atendimento ativo/)).toBeInTheDocument()
  })
})
