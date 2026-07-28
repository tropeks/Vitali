import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import SaePrescription from './SaePrescription'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

const ITEM = {
  id: 'rx-1',
  intervention: 'int-1',
  description: 'Aferir sinais vitais',
  frequency_hours: 6,
  start_at: '2026-07-22T08:00:00Z',
  active: true,
  created_at: '2026-07-22T07:00:00Z',
}

function routeApi(overrides: Record<string, any> = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url.startsWith('/api/v1/nursing-prescription-items/') && opts?.method === 'POST') {
      return Promise.resolve(overrides.post ?? { id: 'rx-new' })
    }
    if (url.startsWith('/api/v1/nursing-prescription-items/')) {
      return Promise.resolve(overrides.list ?? [])
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SaePrescription', () => {
  it('fetches prescription items scoped by intervention', async () => {
    routeApi({ list: [] })
    render(<SaePrescription interventionId="int-1" canWrite={false} />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/nursing-prescription-items/?intervention=int-1'
      )
    })
  })

  it('shows an empty state when there are no items', async () => {
    routeApi({ list: [] })
    render(<SaePrescription interventionId="int-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Sem prescrição de enfermagem')).toBeInTheDocument()
    })
  })

  it('renders an executable item with its frequency', async () => {
    routeApi({ list: [ITEM] })
    render(<SaePrescription interventionId="int-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Aferir sinais vitais')).toBeInTheDocument()
    })
    expect(screen.getByText(/6\s*em\s*6\s*h/i)).toBeInTheDocument()
  })

  it('posts a new prescription item with intervention, frequency and start', async () => {
    routeApi({ list: [] })
    render(<SaePrescription interventionId="int-1" canWrite />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Adicionar prescrição/ })).toBeInTheDocument()
    )
    fireEvent.click(screen.getByRole('button', { name: /Adicionar prescrição/ }))

    fireEvent.change(screen.getByRole('textbox', { name: /Descrição/ }), {
      target: { value: 'Aferir PA' },
    })
    fireEvent.change(screen.getByLabelText(/Frequência/), { target: { value: '8' } })
    fireEvent.change(screen.getByLabelText(/Início/), {
      target: { value: '2026-07-25T08:00' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Salvar prescrição/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) => url === '/api/v1/nursing-prescription-items/' && opts?.method === 'POST'
      )
      expect(postCall).toBeTruthy()
      const body = JSON.parse(postCall![1].body)
      expect(body.intervention).toBe('int-1')
      expect(body.description).toBe('Aferir PA')
      expect(body.frequency_hours).toBe(8)
      expect(body.start_at).toBeTruthy()
    })
  })
})
