import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PlatformTerminologyPage from './page'

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

const IMPORT_STATUS = [
  {
    system: 'cbo',
    row_count: 2712,
    last_import_at: '2026-06-01T10:00:00Z',
    last_import_status: 'success',
    last_import_version: '2026.1',
  },
  {
    system: 'cnes',
    row_count: 0,
    last_import_at: null,
    last_import_status: null,
    last_import_version: null,
  },
  {
    system: 'loinc',
    row_count: 500,
    last_import_at: '2026-05-15T08:00:00Z',
    last_import_status: 'failed',
    last_import_version: '2.76',
  },
  {
    system: 'ucum',
    row_count: 300,
    last_import_at: '2026-04-10T08:00:00Z',
    last_import_status: 'success',
    last_import_version: '2.2',
  },
]

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('PlatformTerminologyPage', () => {
  it('loads and renders one row per catalog with row_count, last import date/status/version', async () => {
    mockApiFetch.mockResolvedValueOnce(IMPORT_STATUS)

    render(<PlatformTerminologyPage />)

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/platform/terminology/import-status/')
    })

    expect(await screen.findByText('CBO')).toBeInTheDocument()
    expect(screen.getByText('CNES')).toBeInTheDocument()
    expect(screen.getByText('LOINC')).toBeInTheDocument()
    expect(screen.getByText('UCUM')).toBeInTheDocument()

    expect(screen.getByText('2.712')).toBeInTheDocument()
    expect(screen.getByText('2026.1')).toBeInTheDocument()
  })

  it('shows all four fixed catalogs with a never-imported placeholder when status is empty', async () => {
    mockApiFetch.mockResolvedValueOnce([])

    render(<PlatformTerminologyPage />)

    await waitFor(() => {
      expect(screen.getByText('CBO')).toBeInTheDocument()
    })

    expect(screen.getByText('CNES')).toBeInTheDocument()
    expect(screen.getByText('LOINC')).toBeInTheDocument()
    expect(screen.getByText('UCUM')).toBeInTheDocument()

    // Four rows, all never imported.
    expect(screen.getAllByText('Nunca importado')).toHaveLength(4)
  })

  it('shows an error state when the status fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Falha de rede'))

    render(<PlatformTerminologyPage />)

    await waitFor(() => {
      expect(screen.getByText('Falha de rede')).toBeInTheDocument()
    })
  })

  it('opens the catalog browser modal when "Ver" is clicked and requests that catalog', async () => {
    mockApiFetch.mockResolvedValueOnce(IMPORT_STATUS)
    mockApiFetch.mockResolvedValueOnce({ results: [], count: 0 })

    render(<PlatformTerminologyPage />)

    await waitFor(() => {
      expect(screen.getByText('CBO')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Ver' })[0])

    await waitFor(() => {
      expect(
        mockApiFetch.mock.calls.some(([url]) =>
          String(url).startsWith('/api/v1/platform/terminology/cbo/'),
        ),
      ).toBe(true)
    })
  })

  it('opens the import modal when "Importar CSV" is clicked', async () => {
    mockApiFetch.mockResolvedValueOnce(IMPORT_STATUS)

    render(<PlatformTerminologyPage />)

    await waitFor(() => {
      expect(screen.getByText('CBO')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Importar CSV' })[0])

    expect(await screen.findByText(/Importar CSV — CBO/)).toBeInTheDocument()
  })
})
