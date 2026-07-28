import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import EmergencyReclassifyModal from './EmergencyReclassifyModal'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

const FLOWCHARTS = [{ id: 'fc-1', code: 'DOR-TORAX', display: 'Dor torácica' }]

const DISCRIMINATORS = [
  {
    id: 'disc-1',
    flowchart: 'fc-1',
    code: 'DOR-PRECORDIAL',
    name: 'Dor pré-cordial',
    acuity_level: 'laranja',
    target_minutes: 10,
  },
]

function routeApi() {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url === '/api/v1/manchester-flowcharts/') return Promise.resolve(FLOWCHARTS)
    if (url.startsWith('/api/v1/manchester-discriminators/?flowchart=')) {
      return Promise.resolve(DISCRIMINATORS)
    }
    if (url.endsWith('/classify/') && opts?.method === 'POST') {
      return Promise.resolve({ id: 'bol-1', status: 'classificado' })
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('EmergencyReclassifyModal', () => {
  it('loads flowcharts, then discriminators, and posts the classify (append)', async () => {
    routeApi()
    const onClassified = vi.fn()
    render(
      <EmergencyReclassifyModal boletimId="bol-1" onClose={() => {}} onClassified={onClassified} />,
    )

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/manchester-flowcharts/')
    })

    fireEvent.change(screen.getByLabelText('Fluxograma'), { target: { value: 'fc-1' } })

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/manchester-discriminators/?flowchart=fc-1',
      )
    })

    fireEvent.change(screen.getByLabelText('Discriminador'), { target: { value: 'disc-1' } })
    // The resulting acuity preview appears from the chosen discriminator.
    expect(screen.getByText('Laranja (muito urgente)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Registrar classificação' }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/emergency-encounters/bol-1/classify/',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    const postCall = mockApiFetch.mock.calls.find(
      ([url]) => url === '/api/v1/emergency-encounters/bol-1/classify/',
    )
    expect(JSON.parse(postCall![1].body)).toMatchObject({ discriminator: 'disc-1' })
    expect(onClassified).toHaveBeenCalled()
  })

  it('validates that a discriminator is chosen before posting', async () => {
    routeApi()
    render(
      <EmergencyReclassifyModal boletimId="bol-1" onClose={() => {}} onClassified={() => {}} />,
    )
    await waitFor(() => screen.getByLabelText('Fluxograma'))

    fireEvent.click(screen.getByRole('button', { name: 'Registrar classificação' }))

    expect(screen.getByText(/Selecione um fluxograma e um discriminador/)).toBeInTheDocument()
    expect(
      mockApiFetch.mock.calls.some(([url]) => String(url).endsWith('/classify/')),
    ).toBe(false)
  })
})
