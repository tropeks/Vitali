import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SuprimentosPage from './page'

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

const DRUG_CONTROLLED = {
  id: 'drug-1',
  name: 'Morfina',
  is_active: true,
  is_controlled: true,
  lead_time_days: 7,
  safety_stock: '100.50',
  reorder_point: '200.00',
  min_refill_interval_days: 30,
}

const DRUG_NON_CONTROLLED = {
  id: 'drug-2',
  name: 'Paracetamol',
  is_active: true,
  is_controlled: false,
  lead_time_days: 3,
  safety_stock: '50.00',
  reorder_point: '100.00',
  min_refill_interval_days: null,
}

const MATERIAL = {
  id: 'mat-1',
  name: 'Seringa 5ml',
  is_active: true,
  lead_time_days: 5,
  safety_stock: '500.00',
  reorder_point: '1000.00',
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

function setupFetchMock(drugs: any[], materials: any[]) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.includes('/pharmacy/drugs/') && !path.match(/\/drugs\/[^/]+\//)) {
      return Promise.resolve({ results: drugs })
    }
    if (path.includes('/pharmacy/materials/') && !path.match(/\/materials\/[^/]+\//)) {
      return Promise.resolve({ results: materials })
    }
    return Promise.resolve({})
  })
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('SuprimentosPage', () => {
  it('renders editable rows for a drug and a material with supply inputs', async () => {
    setupFetchMock([DRUG_CONTROLLED], [MATERIAL])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Morfina')).toBeInTheDocument()
    })

    expect(screen.getByText('Seringa 5ml')).toBeInTheDocument()

    // Drug row: lead_time_days, safety_stock, reorder_point inputs exist
    // Using aria-label or data-testid - we rely on labels/placeholders in the row
    const inputs = screen.getAllByRole('spinbutton')
    // Should have multiple numeric inputs (lead_time_days for drug + material, etc.)
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })

  it('controlled drug shows min_refill_interval_days input; non-controlled drug does not', async () => {
    setupFetchMock([DRUG_CONTROLLED, DRUG_NON_CONTROLLED], [])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Morfina')).toBeInTheDocument()
    })

    expect(screen.getByText('Paracetamol')).toBeInTheDocument()

    // min_refill_interval_days input exists for controlled drug (Morfina row)
    // We use data-testid convention: min_refill_interval_days-drug-1
    expect(screen.getByTestId('min_refill_interval_days-drug-1')).toBeInTheDocument()

    // Not present for non-controlled drug
    expect(screen.queryByTestId('min_refill_interval_days-drug-2')).not.toBeInTheDocument()

    // Materials never have this field — no material test id
    expect(screen.queryByTestId('min_refill_interval_days-mat-1')).not.toBeInTheDocument()
  })

  it('editing a field and clicking Salvar calls PATCH with correct payload (drug)', async () => {
    const user = userEvent.setup()

    setupFetchMock([DRUG_NON_CONTROLLED], [])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Paracetamol')).toBeInTheDocument()
    })

    // Edit lead_time_days field for drug-2
    const leadTimeInput = screen.getByTestId('lead_time_days-drug-2')
    await user.clear(leadTimeInput)
    await user.type(leadTimeInput, '10')

    // Set up mock for PATCH + reload
    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path === '/api/v1/pharmacy/drugs/drug-2/' && opts?.method === 'PATCH') {
        return Promise.resolve({})
      }
      if (path.includes('/pharmacy/drugs/') && !path.match(/\/drugs\/[^/]+\//)) {
        return Promise.resolve({ results: [DRUG_NON_CONTROLLED] })
      }
      if (path.includes('/pharmacy/materials/')) {
        return Promise.resolve({ results: [] })
      }
      return Promise.resolve({})
    })

    const salvarButtons = screen.getAllByRole('button', { name: 'Salvar' })
    await user.click(salvarButtons[0])

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/drugs/drug-2/',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.stringContaining('"lead_time_days":10'),
        })
      )
    })
  })

  it('editing a field and clicking Salvar calls PATCH for material', async () => {
    const user = userEvent.setup()

    setupFetchMock([], [MATERIAL])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Seringa 5ml')).toBeInTheDocument()
    })

    // Edit safety_stock for mat-1
    const safetyStockInput = screen.getByTestId('safety_stock-mat-1')
    await user.clear(safetyStockInput)
    await user.type(safetyStockInput, '999.99')

    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path === '/api/v1/pharmacy/materials/mat-1/' && opts?.method === 'PATCH') {
        return Promise.resolve({})
      }
      if (path.includes('/pharmacy/drugs/')) {
        return Promise.resolve({ results: [] })
      }
      if (path.includes('/pharmacy/materials/') && !path.match(/\/materials\/[^/]+\//)) {
        return Promise.resolve({ results: [MATERIAL] })
      }
      return Promise.resolve({})
    })

    const salvarButtons = screen.getAllByRole('button', { name: 'Salvar' })
    await user.click(salvarButtons[0])

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/materials/mat-1/',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.stringContaining('"safety_stock":"999.99"'),
        })
      )
    })
  })

  it('blank input sends null (not empty string) in PATCH payload', async () => {
    const user = userEvent.setup()

    // Drug with existing safety_stock value
    const drugWithStock = { ...DRUG_NON_CONTROLLED, safety_stock: '50.00' }
    setupFetchMock([drugWithStock], [])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Paracetamol')).toBeInTheDocument()
    })

    // Clear the safety_stock input (blank → should send null)
    const safetyStockInput = screen.getByTestId('safety_stock-drug-2')
    await user.clear(safetyStockInput)

    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path === '/api/v1/pharmacy/drugs/drug-2/' && opts?.method === 'PATCH') {
        return Promise.resolve({})
      }
      if (path.includes('/pharmacy/drugs/') && !path.match(/\/drugs\/[^/]+\//)) {
        return Promise.resolve({ results: [drugWithStock] })
      }
      if (path.includes('/pharmacy/materials/')) {
        return Promise.resolve({ results: [] })
      }
      return Promise.resolve({})
    })

    const salvarButtons = screen.getAllByRole('button', { name: 'Salvar' })
    await user.click(salvarButtons[0])

    await waitFor(() => {
      const patchCall = mockApiFetch.mock.calls.find(
        (call) => call[0] === '/api/v1/pharmacy/drugs/drug-2/' && call[1]?.method === 'PATCH'
      )
      expect(patchCall).toBeDefined()
      const body = JSON.parse(patchCall![1].body)
      expect(body.safety_stock).toBeNull()
    })
  })

  it('decimal values sent as the string the user typed (no Number() coercion)', async () => {
    const user = userEvent.setup()

    setupFetchMock([DRUG_NON_CONTROLLED], [])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Paracetamol')).toBeInTheDocument()
    })

    const reorderInput = screen.getByTestId('reorder_point-drug-2')
    await user.clear(reorderInput)
    await user.type(reorderInput, '123.45')

    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path === '/api/v1/pharmacy/drugs/drug-2/' && opts?.method === 'PATCH') {
        return Promise.resolve({})
      }
      if (path.includes('/pharmacy/drugs/') && !path.match(/\/drugs\/[^/]+\//)) {
        return Promise.resolve({ results: [DRUG_NON_CONTROLLED] })
      }
      if (path.includes('/pharmacy/materials/')) {
        return Promise.resolve({ results: [] })
      }
      return Promise.resolve({})
    })

    const salvarButtons = screen.getAllByRole('button', { name: 'Salvar' })
    await user.click(salvarButtons[0])

    await waitFor(() => {
      const patchCall = mockApiFetch.mock.calls.find(
        (call) => call[0] === '/api/v1/pharmacy/drugs/drug-2/' && call[1]?.method === 'PATCH'
      )
      expect(patchCall).toBeDefined()
      const body = JSON.parse(patchCall![1].body)
      // Should be a string "123.45", not the number 123.45
      expect(body.reorder_point).toBe('123.45')
    })
  })

  it('renders empty state when both lists are empty', async () => {
    setupFetchMock([], [])

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum medicamento cadastrado.')).toBeInTheDocument()
    })
    expect(screen.getByText('Nenhum material cadastrado.')).toBeInTheDocument()
  })

  it('renders error state when initial fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))

    render(<SuprimentosPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar dados.')).toBeInTheDocument()
    })
  })
})
