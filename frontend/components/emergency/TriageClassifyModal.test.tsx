import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import TriageClassifyModal from './TriageClassifyModal'

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

const DISCRIMINATORS = [
  {
    id: 'd1',
    flowchart: 'fc1',
    code: 'DPC',
    name: 'Dor pré-cordial',
    acuity_level: 'laranja',
    target_minutes: 10,
  },
  {
    id: 'd2',
    flowchart: 'fc1',
    code: 'DL',
    name: 'Dor leve',
    acuity_level: 'verde',
    target_minutes: 120,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/manchester-flowcharts/')) {
      return Promise.resolve({ results: [{ id: 'fc1', code: 'DT', display: 'Dor torácica' }], next: null })
    }
    if (url.startsWith('/api/v1/manchester-discriminators/')) {
      return Promise.resolve({ results: DISCRIMINATORS, next: null })
    }
    return Promise.resolve({ id: 'b1' })
  })
})

describe('TriageClassifyModal', () => {
  it('loads discriminators for the chosen fluxograma, shows the acuidade and posts classify', async () => {
    const onClassified = vi.fn()
    render(
      <TriageClassifyModal
        boletimId="b1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onClassified={onClassified}
      />,
    )

    // Pick a fluxograma → triggers the discriminators fetch (?flowchart=fc1).
    fireEvent.focus(screen.getByRole('combobox', { name: 'Fluxograma' }))
    fireEvent.click(await screen.findByRole('option', { name: 'DT — Dor torácica' }))

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/manchester-discriminators/?flowchart=fc1'),
    )

    // Select a discriminador — the acuidade it dispara is shown.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: 'Dor pré-cordial (Laranja)' })).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText('Discriminador'), { target: { value: 'd1' } })

    expect(screen.getByText('Laranja (muito urgente)')).toBeInTheDocument()
    expect(screen.getByText('Tempo-alvo: 10min')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Classificar' }))

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/b1/classify/',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
    const call = mockApiFetch.mock.calls.find(([u]) => u === '/api/v1/emergency-encounters/b1/classify/')!
    expect(JSON.parse((call[1] as any).body)).toEqual({ discriminator: 'd1' })
    expect(onClassified).toHaveBeenCalled()
  })

  it('requires a discriminador before posting', async () => {
    render(
      <TriageClassifyModal
        boletimId="b1"
        patientName="Maria Silva"
        onClose={vi.fn()}
        onClassified={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Classificar' }))
    expect(await screen.findByText('Selecione um discriminador para classificar.')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalledWith(
      '/api/v1/emergency-encounters/b1/classify/',
      expect.anything(),
    )
  })
})
