/**
 * Vitest + @testing-library/react tests for CargosPage (Position CRUD).
 *
 * Run: npx vitest run app/\(dashboard\)/rh/cargos
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import CargosPage from './page'

// ─── Mocks ────────────────────────────────────────────────────────────────────

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

// ─── Sample data ──────────────────────────────────────────────────────────────

const POSITION_1 = {
  id: 'pos-1',
  title: 'Recepcionista',
  cbo: '4221-05',
  active: true,
  created_at: '2024-01-15T10:00:00Z',
  updated_at: '2024-01-15T10:00:00Z',
}

const POSITION_2 = {
  id: 'pos-2',
  title: 'Auxiliar de Limpeza',
  cbo: '',
  active: false,
  created_at: '2023-06-01T08:00:00Z',
  updated_at: '2023-06-01T08:00:00Z',
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('CargosPage', () => {
  it('renders empty state when no positions', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<CargosPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum cargo cadastrado ainda.')).toBeInTheDocument()
    })
  })

  it('renders position rows when data loads', async () => {
    mockApiFetch.mockResolvedValueOnce([POSITION_1, POSITION_2])

    render(<CargosPage />)

    await waitFor(() => {
      expect(screen.getByText('Recepcionista')).toBeInTheDocument()
    })

    expect(screen.getByText('Auxiliar de Limpeza')).toBeInTheDocument()
    expect(screen.getByText('4221-05')).toBeInTheDocument()
    expect(screen.getByText('Ativo')).toBeInTheDocument()
    expect(screen.getByText('Inativo')).toBeInTheDocument()
  })

  it('error state shown when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Network error'))

    render(<CargosPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar cargos.')).toBeInTheDocument()
    })
  })

  it('create form submits POST with correct payload', async () => {
    mockApiFetch.mockResolvedValueOnce([]) // initial load

    render(<CargosPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum cargo cadastrado ainda.')).toBeInTheDocument()
    })

    mockApiFetch.mockResolvedValueOnce({
      id: 'pos-3',
      title: 'Farmacêutico',
      cbo: '2234-05',
      active: true,
      created_at: '2024-02-01T00:00:00Z',
      updated_at: '2024-02-01T00:00:00Z',
    })
    mockApiFetch.mockResolvedValueOnce([]) // reload after create

    fireEvent.click(screen.getAllByRole('button', { name: /novo cargo/i })[0])

    fireEvent.change(screen.getByLabelText(/título/i), {
      target: { value: 'Farmacêutico' },
    })
    fireEvent.change(screen.getByLabelText(/cbo/i), {
      target: { value: '2234-05' },
    })

    fireEvent.click(screen.getByRole('button', { name: /cadastrar cargo/i }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/hr/positions/', {
        method: 'POST',
        body: JSON.stringify({ title: 'Farmacêutico', cbo: '2234-05', active: true }),
      })
    })
  })
})
