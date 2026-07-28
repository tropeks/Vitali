import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import SusCompetenciaList from './SusCompetenciaList'

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

const FACILITIES = [
  { id: 'f1', name: 'UBS Central' },
  { id: 'f2', name: 'Hospital Municipal' },
]

const COMPETENCIAS = [
  { id: 1, establishment: 'f1', competencia: '2026-07', status: 'aberta' },
]

function routeApi(overrides: { postCreate?: () => any } = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
    if (url.startsWith('/api/v1/billing/sus-competencias/') && opts?.method === 'POST') {
      return Promise.resolve(overrides.postCreate ? overrides.postCreate() : { id: 2 })
    }
    if (url.startsWith('/api/v1/billing/sus-competencias/')) {
      return Promise.resolve(COMPETENCIAS)
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SusCompetenciaList', () => {
  it('renders competências with facility name + status badge', async () => {
    routeApi()
    render(<SusCompetenciaList canWrite={false} onSelect={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('2026-07')).toBeInTheDocument())
    // "UBS Central" / "Aberta" also appear as filter <option>s — assert presence.
    expect(screen.getAllByText('UBS Central').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Aberta').length).toBeGreaterThan(0)
  })

  it('opens the detail when a row is selected', async () => {
    routeApi()
    const onSelect = vi.fn()
    render(<SusCompetenciaList canWrite={false} onSelect={onSelect} />)
    await waitFor(() => expect(screen.getByText('2026-07')).toBeInTheDocument())
    fireEvent.click(screen.getByText('2026-07'))
    expect(onSelect).toHaveBeenCalledWith(1)
  })

  it('hides the create form without sus.write', async () => {
    routeApi()
    render(<SusCompetenciaList canWrite={false} onSelect={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('2026-07')).toBeInTheDocument())
    expect(screen.queryByText('Nova competência')).not.toBeInTheDocument()
  })

  it('creates a competência (POST payload) and opens it (gated sus.write)', async () => {
    routeApi({ postCreate: () => ({ id: 42, establishment: 'f1', competencia: '2026-08' }) })
    const onSelect = vi.fn()
    render(<SusCompetenciaList canWrite onSelect={onSelect} />)
    await waitFor(() => expect(screen.getByText('Nova competência')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('Estabelecimento da nova competência'), {
      target: { value: 'f1' },
    })
    fireEvent.change(screen.getByLabelText('Competência (AAAA-MM)'), {
      target: { value: '2026-08' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Criar competência/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) =>
          url === '/api/v1/billing/sus-competencias/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    const postCall = mockApiFetch.mock.calls.find(
      ([url, opts]) => url === '/api/v1/billing/sus-competencias/' && opts?.method === 'POST',
    )
    const body = JSON.parse(postCall![1].body)
    expect(body).toEqual({ establishment: 'f1', competencia: '2026-08' })
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(42))
  })

  it('refetches with establishment + status query filters', async () => {
    routeApi()
    render(<SusCompetenciaList canWrite={false} onSelect={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('2026-07')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('Filtrar por situação'), {
      target: { value: 'fechada' },
    })
    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/billing/sus-competencias/?status=fechada'),
    )
  })
})
