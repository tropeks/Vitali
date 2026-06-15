import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AISettingsPage from './page'

// ─── Mocks ────────────────────────────────────────────────────────────────────

// Mock @/lib/auth — the page uses getAccessToken() directly
vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

// DPASignModal is not the focus — stub it out
vi.mock('@/components/settings/DPASignModal', () => ({
  DPASignModal: () => null,
}))

// ─── Sample data ──────────────────────────────────────────────────────────────

const DPA_STATUS_SIGNED = {
  is_signed: true,
  signed_at: '2024-01-15',
  signed_by_name: 'Dr. Admin',
  ai_scribe_enabled: false,
  current_user_can_sign: false,
}

const DPA_STATUS_UNSIGNED = {
  is_signed: false,
  signed_at: null,
  signed_by_name: null,
  ai_scribe_enabled: false,
  current_user_can_sign: true,
}

const READINESS_TWO_WEDGES = {
  wedges: [
    {
      key: 'drugs',
      label: 'Medicamentos',
      total: 10,
      ready_count: 10,
      blockers: [],
      ready_text: 'Todos os medicamentos prontos',
    },
    {
      key: 'materials',
      label: 'Materiais',
      total: 5,
      ready_count: 3,
      blockers: ['Seringa 5ml sem estoque de segurança', 'Luva sem ponto de reposição'],
      ready_text: 'Todos os materiais prontos',
    },
  ],
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.restoreAllMocks()
})

function mockFetchRouted(dpaPayload: object, readinessPayload: object) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (String(url).includes('/pharmacy/curation/readiness/')) {
        return {
          ok: true,
          json: async () => readinessPayload,
        } as Response
      }
      // Default: DPA endpoint
      return {
        ok: true,
        json: async () => dpaPayload,
      } as Response
    })
  )
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('AISettingsPage — readiness section', () => {
  it('renders both wedge titles when readiness returns 2 wedges', async () => {
    mockFetchRouted(DPA_STATUS_SIGNED, READINESS_TWO_WEDGES)

    render(<AISettingsPage />)

    await waitFor(() => {
      expect(screen.getByText('Medicamentos')).toBeInTheDocument()
    })

    expect(screen.getByText('Materiais')).toBeInTheDocument()
  })

  it('renders ready_text for the clean wedge (no blockers)', async () => {
    mockFetchRouted(DPA_STATUS_SIGNED, READINESS_TWO_WEDGES)

    render(<AISettingsPage />)

    await waitFor(() => {
      expect(screen.getByText('Todos os medicamentos prontos')).toBeInTheDocument()
    })
  })

  it('renders blocker text for the blocked wedge', async () => {
    mockFetchRouted(DPA_STATUS_SIGNED, READINESS_TWO_WEDGES)

    render(<AISettingsPage />)

    await waitFor(() => {
      expect(screen.getByText('Seringa 5ml sem estoque de segurança')).toBeInTheDocument()
    })

    expect(screen.getByText('Luva sem ponto de reposição')).toBeInTheDocument()
  })

  it('renders ready_count/total counts for each wedge', async () => {
    mockFetchRouted(DPA_STATUS_SIGNED, READINESS_TWO_WEDGES)

    render(<AISettingsPage />)

    // 10/10 prontos for drugs wedge
    await waitFor(() => {
      expect(screen.getByText('10/10 prontos')).toBeInTheDocument()
    })

    // 3/5 prontos for materials wedge
    expect(screen.getByText('3/5 prontos')).toBeInTheDocument()
  })

  it('renders the readiness section heading', async () => {
    mockFetchRouted(DPA_STATUS_SIGNED, READINESS_TWO_WEDGES)

    render(<AISettingsPage />)

    await waitFor(() => {
      expect(screen.getByText('Prontidão de curadoria de dados')).toBeInTheDocument()
    })
  })

  it('page still renders without crashing when DPA is unsigned and readiness loads', async () => {
    mockFetchRouted(DPA_STATUS_UNSIGNED, READINESS_TWO_WEDGES)

    render(<AISettingsPage />)

    await waitFor(() => {
      // Page renders — DPA section shows sign prompt
      expect(screen.getByText(/Assinar DPA/i)).toBeInTheDocument()
    })

    // Readiness section also loaded
    await waitFor(() => {
      expect(screen.getByText('Medicamentos')).toBeInTheDocument()
    })
  })

  it('handles empty wedges gracefully (no crash)', async () => {
    mockFetchRouted(DPA_STATUS_SIGNED, { wedges: [] })

    render(<AISettingsPage />)

    await waitFor(() => {
      expect(screen.getByText('Prontidão de curadoria de dados')).toBeInTheDocument()
    })
  })
})
