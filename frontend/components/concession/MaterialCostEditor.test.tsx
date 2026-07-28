import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import MaterialCostEditor from './MaterialCostEditor'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
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

const MATERIALS = [
  { id: 'm1', name: 'Contraste Iodado', unit_of_measure: 'ml' },
  { id: 'm2', name: 'Filme Radiográfico', unit_of_measure: 'un' },
]
const COSTS = [{ id: 1, material: 'm1', unit_cost: '12.50' }]

function routeReads() {
  mockApiFetch.mockImplementation((path: string, opts?: any) => {
    if (path.startsWith('/api/v1/concession/material-unit-costs/') && (!opts || opts.method === undefined))
      return Promise.resolve({ count: COSTS.length, results: COSTS })
    if (path.startsWith('/api/v1/pharmacy/materials/'))
      return Promise.resolve({ count: MATERIALS.length, results: MATERIALS })
    return Promise.resolve({ results: [] })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('MaterialCostEditor', () => {
  it('lists existing unit costs, resolving the material name and BRL value', async () => {
    routeReads()
    render(<MaterialCostEditor />)

    await waitFor(() => {
      expect(screen.getByText('Contraste Iodado')).toBeInTheDocument()
    })
    expect(screen.getByText('R$ 12,50')).toBeInTheDocument()
  })

  it('POSTs { material, unit_cost } when adding a new material cost', async () => {
    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path.startsWith('/api/v1/concession/material-unit-costs/') && opts?.method === 'POST')
        return Promise.resolve({ id: 2, material: 'm2', unit_cost: '3.20' })
      if (path.startsWith('/api/v1/concession/material-unit-costs/'))
        return Promise.resolve({ count: COSTS.length, results: COSTS })
      if (path.startsWith('/api/v1/pharmacy/materials/'))
        return Promise.resolve({ count: MATERIALS.length, results: MATERIALS })
      return Promise.resolve({ results: [] })
    })

    render(<MaterialCostEditor />)

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /Filme Radiográfico/ })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Material/i), { target: { value: 'm2' } })
    fireEvent.change(screen.getByLabelText(/Custo unitário/i), { target: { value: '3.20' } })
    fireEvent.click(screen.getByRole('button', { name: /Adicionar/i }))

    await waitFor(() => {
      const post = mockApiFetch.mock.calls.find(
        (c) => c[0] === '/api/v1/concession/material-unit-costs/' && c[1]?.method === 'POST'
      )
      expect(post).toBeTruthy()
    })

    const post = mockApiFetch.mock.calls.find(
      (c) => c[0] === '/api/v1/concession/material-unit-costs/' && c[1]?.method === 'POST'
    )
    expect(JSON.parse(post![1].body)).toEqual({ material: 'm2', unit_cost: '3.20' })
  })

  it('PUTs to the detail endpoint with { material, unit_cost } when editing a row', async () => {
    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path === '/api/v1/concession/material-unit-costs/1/' && opts?.method === 'PUT')
        return Promise.resolve({ id: 1, material: 'm1', unit_cost: '99.00' })
      if (path.startsWith('/api/v1/concession/material-unit-costs/'))
        return Promise.resolve({ count: COSTS.length, results: COSTS })
      if (path.startsWith('/api/v1/pharmacy/materials/'))
        return Promise.resolve({ count: MATERIALS.length, results: MATERIALS })
      return Promise.resolve({ results: [] })
    })

    render(<MaterialCostEditor />)

    await waitFor(() => {
      expect(screen.getByText('Contraste Iodado')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Editar/i }))
    const input = await screen.findByLabelText(/Editar custo de Contraste Iodado/i)
    fireEvent.change(input, { target: { value: '99.00' } })
    fireEvent.click(screen.getByRole('button', { name: /Salvar/i }))

    await waitFor(() => {
      const put = mockApiFetch.mock.calls.find(
        (c) => c[0] === '/api/v1/concession/material-unit-costs/1/' && c[1]?.method === 'PUT'
      )
      expect(put).toBeTruthy()
    })

    const put = mockApiFetch.mock.calls.find(
      (c) => c[0] === '/api/v1/concession/material-unit-costs/1/' && c[1]?.method === 'PUT'
    )
    expect(JSON.parse(put![1].body)).toEqual({ material: 'm1', unit_cost: '99.00' })
  })

  it('shows an error state when the load fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<MaterialCostEditor />)
    await waitFor(() => {
      expect(screen.getByText(/Erro ao carregar custos de material/i)).toBeInTheDocument()
    })
  })
})
