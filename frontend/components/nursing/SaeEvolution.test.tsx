import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import SaeEvolution from './SaeEvolution'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

const EVO = {
  id: 'evo-1',
  patient: 'patient-1',
  encounter: 'enc-1',
  text: 'Paciente evoluindo com melhora da dor.',
  created_at: '2026-07-22T14:30:00Z',
}

function routeApi(overrides: Record<string, any> = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url.startsWith('/api/v1/nursing-evolutions/') && opts?.method === 'POST') {
      return Promise.resolve(overrides.post ?? { id: 'evo-new' })
    }
    if (url.startsWith('/api/v1/nursing-evolutions/')) {
      return Promise.resolve(overrides.list ?? [])
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SaeEvolution', () => {
  it('fetches evolutions scoped by patient', async () => {
    routeApi({ list: [] })
    render(<SaeEvolution patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/nursing-evolutions/?patient=patient-1')
    })
  })

  it('shows an empty state when there are no evolutions', async () => {
    routeApi({ list: [] })
    render(<SaeEvolution patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Sem evolução de enfermagem')).toBeInTheDocument()
    })
  })

  it('renders evolution notes', async () => {
    routeApi({ list: [EVO] })
    render(<SaeEvolution patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Paciente evoluindo com melhora da dor.')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<SaeEvolution patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar evoluções')).toBeInTheDocument()
    })
  })

  it('hides the add control without sae.write', async () => {
    routeApi({ list: [] })
    render(<SaeEvolution patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Sem evolução de enfermagem')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Adicionar evolução/ })).not.toBeInTheDocument()
  })

  it('posts a new evolution with encounter and text', async () => {
    routeApi({ list: [] })
    render(<SaeEvolution patientId="patient-1" encounterId="enc-1" canWrite />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Adicionar evolução/ })).toBeInTheDocument()
    )
    fireEvent.click(screen.getByRole('button', { name: /Adicionar evolução/ }))

    fireEvent.change(screen.getByRole('textbox', { name: /Evolução/ }), {
      target: { value: 'Evolução de enfermagem do plantão.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Salvar evolução/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) => url === '/api/v1/nursing-evolutions/' && opts?.method === 'POST'
      )
      expect(postCall).toBeTruthy()
      const body = JSON.parse(postCall![1].body)
      expect(body.text).toBe('Evolução de enfermagem do plantão.')
      expect(body.encounter).toBe('enc-1')
    })
  })
})
