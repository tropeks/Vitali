import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ProfissionaisPage from './page'

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

const PROFESSIONAL_1 = {
  id: 'pro-1',
  user: 'user-1',
  user_name: 'Dra. Ana Souza',
  user_email: 'ana@clinica.com',
  council_type: 'CRM',
  council_type_display: 'CRM',
  council_number: '12345',
  council_state: 'SP',
  specialty: 'Clínica Médica',
  cbo_code: '2231-05',
  cnes_code: null,
  cbo_unmatched: false,
  cnes_unmatched: false,
  is_active: true,
  created_at: '2024-01-15T10:00:00Z',
}

const PROFESSIONAL_2 = {
  id: 'pro-2',
  user: 'user-2',
  user_name: 'Dr. Bruno Lima',
  user_email: 'bruno@clinica.com',
  council_type: 'CRO',
  council_type_display: 'CRO',
  council_number: '67890',
  council_state: 'RJ',
  specialty: 'Odontologia',
  cbo_code: null,
  cnes_code: '9999999',
  cbo_unmatched: false,
  cnes_unmatched: true,
  is_active: false,
  created_at: '2023-06-01T08:00:00Z',
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('ProfissionaisPage', () => {
  it('renders empty state when no professionals', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<ProfissionaisPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum profissional cadastrado ainda.')).toBeInTheDocument()
    })

    expect(
      screen.getByText(/Profissionais são criados automaticamente/)
    ).toBeInTheDocument()
  })

  it('renders professional rows when data loads', async () => {
    mockApiFetch.mockResolvedValueOnce([PROFESSIONAL_1, PROFESSIONAL_2])

    render(<ProfissionaisPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })

    expect(screen.getByText('Dr. Bruno Lima')).toBeInTheDocument()

    // Council display format
    expect(screen.getByText('CRM 12345/SP')).toBeInTheDocument()
    expect(screen.getByText('CRO 67890/RJ')).toBeInTheDocument()

    // Specialty
    expect(screen.getByText('Clínica Médica')).toBeInTheDocument()
    expect(screen.getByText('Odontologia')).toBeInTheDocument()

    // Status badges
    expect(screen.getByText('Ativo')).toBeInTheDocument()
    expect(screen.getByText('Inativo')).toBeInTheDocument()
  })

  it('error state shown when fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Network error'))

    render(<ProfissionaisPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar profissionais.')).toBeInTheDocument()
    })
  })

  it('inactive professional shows red badge', async () => {
    mockApiFetch.mockResolvedValueOnce([PROFESSIONAL_2])

    render(<ProfissionaisPage />)

    await waitFor(() => {
      expect(screen.getByText('Dr. Bruno Lima')).toBeInTheDocument()
    })

    const badge = screen.getByText('Inativo')
    expect(badge.className).toContain('bg-red-100')
    expect(badge.className).toContain('text-red-700')
  })

  it('shows governed CBO/CNES codes and an unmatched badge when reconciliation failed', async () => {
    mockApiFetch.mockResolvedValueOnce([PROFESSIONAL_1, PROFESSIONAL_2])

    render(<ProfissionaisPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })

    // Reconciled CBO for professional 1 — no warning badge.
    expect(screen.getByText('2231-05')).toBeInTheDocument()
    // Unreconciled CNES for professional 2 — warning badge shown.
    expect(screen.getByText('9999999')).toBeInTheDocument()
    expect(screen.getByText('não reconciliado')).toBeInTheDocument()
  })

  it('opens the edit modal and PATCHes cbo_code/cnes_code on save', async () => {
    mockApiFetch.mockResolvedValueOnce([PROFESSIONAL_1])

    render(<ProfissionaisPage />)

    await waitFor(() => {
      expect(screen.getByText('Dra. Ana Souza')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Editar' })[0])

    expect(await screen.findByRole('button', { name: 'Salvar' })).toBeInTheDocument()

    mockApiFetch.mockResolvedValueOnce({ ...PROFESSIONAL_1, cbo_code: '2231-05', cnes_code: null })

    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => {
      const patchCall = mockApiFetch.mock.calls.find(([url]) => url === '/api/v1/professionals/pro-1/')
      expect(patchCall).toBeTruthy()
    })

    const patchCall = mockApiFetch.mock.calls.find(([url]) => url === '/api/v1/professionals/pro-1/')
    const [, init] = patchCall!
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ cbo_code: '2231-05', cnes_code: '' })
  })
})
