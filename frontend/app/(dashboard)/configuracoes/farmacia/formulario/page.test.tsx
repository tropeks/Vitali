import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FormularioPage from './page'

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

const RULE_VALIDATED = {
  id: 'dr-1',
  drug_name: 'Paracetamol',
  basis: 'weight',
  dose_unit: 'mg',
  min_per_kg: 10,
  max_per_kg: 15,
  min_per_dose: null,
  max_per_dose: null,
  absolute_max_dose: 1000,
  active: true,
  validated: true,
  validated_by: 'Dr. João',
  validated_at: '2024-03-01T10:00:00Z',
}

const RULE_UNVALIDATED = {
  id: 'dr-2',
  drug_name: 'Ibuprofeno',
  basis: 'weight',
  dose_unit: 'mg',
  min_per_kg: 5,
  max_per_kg: 10,
  min_per_dose: null,
  max_per_dose: null,
  absolute_max_dose: 400,
  active: true,
  validated: false,
  validated_by: null,
  validated_at: null,
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('FormularioPage', () => {
  it('renders empty state when apiFetch resolves with empty list', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<FormularioPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhuma regra de dose cadastrada.')).toBeInTheDocument()
    })
  })

  it('renders rows with validated and unvalidated rules', async () => {
    mockApiFetch.mockResolvedValueOnce([RULE_VALIDATED, RULE_UNVALIDATED])

    render(<FormularioPage />)

    await waitFor(() => {
      expect(screen.getByText('Paracetamol')).toBeInTheDocument()
    })

    // Both drug names visible
    expect(screen.getByText('Ibuprofeno')).toBeInTheDocument()

    // Validated row shows "Validada" indicator (badge — column header also says "Validada")
    const validadaElements = screen.getAllByText('Validada')
    expect(validadaElements.length).toBeGreaterThanOrEqual(2) // header + badge

    // Unvalidated row shows "Validar" button
    expect(screen.getByRole('button', { name: 'Validar' })).toBeInTheDocument()
  })

  it('clicking Validar calls apiFetch with POST to validate endpoint then reloads', async () => {
    const user = userEvent.setup()

    // 1st call: initial list load
    mockApiFetch.mockResolvedValueOnce([RULE_VALIDATED, RULE_UNVALIDATED])
    // 2nd call: validate POST
    mockApiFetch.mockResolvedValueOnce(undefined)
    // 3rd call: reload list
    mockApiFetch.mockResolvedValueOnce([RULE_VALIDATED, RULE_UNVALIDATED])

    render(<FormularioPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Validar' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Validar' }))

    await waitFor(() => {
      // validate POST called with correct path and method
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/dose-rules/dr-2/validate/',
        { method: 'POST' }
      )
    })

    // reload list called (3rd call)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledTimes(3)
    })

    // 3rd call was a GET of the list
    expect(mockApiFetch).toHaveBeenNthCalledWith(3, '/api/v1/pharmacy/dose-rules/')
  })

  it('renders error state when initial fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Network error'))

    render(<FormularioPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar regras de dose.')).toBeInTheDocument()
    })
  })
})
