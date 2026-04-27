import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
  cbo_code: null,
  cnes_code: null,
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
  cnes_code: null,
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
})
