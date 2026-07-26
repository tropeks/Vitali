/**
 * Vitest + @testing-library/react tests for DependentesPage (Dependent CRUD).
 *
 * Run: npx vitest run app/\(dashboard\)/rh/dependentes
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import DependentesPage from './page'

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

const EMPLOYEE_1 = {
  id: 'emp-1',
  user: 'user-1',
  full_name: 'Maria Silva',
  email: 'maria@clinica.com',
  role: 'recepcao',
  employment_status: 'active',
  hire_date: '2020-01-01',
  contract_type: 'clt',
  terminated_at: null,
  created_at: '2020-01-01T10:00:00Z',
}

const EMPLOYEE_2 = {
  id: 'emp-2',
  user: 'user-2',
  full_name: 'João Souza',
  email: 'joao@clinica.com',
  role: 'medico',
  employment_status: 'active',
  hire_date: '2019-01-01',
  contract_type: 'clt',
  terminated_at: null,
  created_at: '2019-01-01T10:00:00Z',
}

const DEPENDENT_1 = {
  id: 'dep-1',
  employee: 'emp-1',
  full_name: 'Ana Silva',
  relationship: 'child',
  birth_date: '2015-03-10',
  cpf: '',
  is_income_tax_dependent: true,
  created_at: '2024-01-01T10:00:00Z',
}

const DEPENDENT_2 = {
  id: 'dep-2',
  employee: 'emp-2',
  full_name: 'Carla Souza',
  relationship: 'spouse',
  birth_date: null,
  cpf: '12345678900',
  is_income_tax_dependent: false,
  created_at: '2023-06-01T08:00:00Z',
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('DependentesPage', () => {
  it('renders empty state when no dependents', async () => {
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1]) // employees
    mockApiFetch.mockResolvedValueOnce([]) // dependents

    render(<DependentesPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum dependente cadastrado ainda.')).toBeInTheDocument()
    })
  })

  it('renders dependent rows when data loads', async () => {
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1, EMPLOYEE_2]) // employees
    mockApiFetch.mockResolvedValueOnce([DEPENDENT_1, DEPENDENT_2]) // dependents

    render(<DependentesPage />)

    await waitFor(() => {
      expect(screen.getByText('Ana Silva')).toBeInTheDocument()
    })

    expect(screen.getByText('Carla Souza')).toBeInTheDocument()
    // Employee names resolved (scoped to the table — names also appear in the filter <select>)
    const table = within(screen.getByRole('table'))
    expect(table.getByText('Maria Silva')).toBeInTheDocument()
    expect(table.getByText('João Souza')).toBeInTheDocument()
    // Relationship pt-BR labels
    expect(table.getByText('Filho(a)')).toBeInTheDocument()
    expect(table.getByText('Cônjuge/companheiro(a)')).toBeInTheDocument()
  })

  it('error state shown when dependents fetch fails', async () => {
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1]) // employees ok
    mockApiFetch.mockRejectedValueOnce(new Error('Network error')) // dependents fail

    render(<DependentesPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar dependentes.')).toBeInTheDocument()
    })
  })

  it('create form submits POST with correct payload', async () => {
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1]) // employees (initial)
    mockApiFetch.mockResolvedValueOnce([]) // dependents (initial, empty)

    render(<DependentesPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum dependente cadastrado ainda.')).toBeInTheDocument()
    })

    mockApiFetch.mockResolvedValueOnce({
      id: 'dep-3',
      employee: 'emp-1',
      full_name: 'João Filho',
      relationship: 'child',
      birth_date: null,
      cpf: '',
      is_income_tax_dependent: false,
      created_at: '2024-03-01T00:00:00Z',
    }) // create response
    mockApiFetch.mockResolvedValueOnce([EMPLOYEE_1]) // reload employees
    mockApiFetch.mockResolvedValueOnce([]) // reload dependents

    fireEvent.click(screen.getAllByRole('button', { name: /novo dependente/i })[0])

    fireEvent.change(screen.getByLabelText(/^funcionário/i), {
      target: { value: 'emp-1' },
    })
    fireEvent.change(screen.getByLabelText(/nome do dependente/i), {
      target: { value: 'João Filho' },
    })

    fireEvent.click(screen.getByRole('button', { name: /cadastrar dependente/i }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/hr/dependents/', {
        method: 'POST',
        body: JSON.stringify({
          employee: 'emp-1',
          full_name: 'João Filho',
          relationship: 'child',
          birth_date: null,
          cpf: '',
          is_income_tax_dependent: false,
        }),
      })
    })
  })
})
