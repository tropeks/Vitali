import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import CatalogBrowser from './CatalogBrowser'

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

const CBO_ITEMS = [
  { id: '1', code: '2231-05', description: 'Médico clínico' },
  { id: '2', code: '2231-10', description: 'Médico cardiologista' },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CatalogBrowser', () => {
  it('loads and renders catalog items from the correct system endpoint', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: CBO_ITEMS, count: 2 })

    render(<CatalogBrowser system="cbo" label="CBO" onClose={() => {}} />)

    await waitFor(() => {
      expect(
        mockApiFetch.mock.calls.some(([url]) =>
          String(url).startsWith('/api/v1/platform/terminology/cbo/'),
        ),
      ).toBe(true)
    })

    expect(await screen.findByText('2231-05')).toBeInTheDocument()
    expect(screen.getByText('Médico clínico')).toBeInTheDocument()
    expect(screen.getByText('2231-10')).toBeInTheDocument()
  })

  it('shows an empty state when no items match', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: [], count: 0 })

    render(<CatalogBrowser system="cnes" label="CNES" onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('Nenhum item encontrado')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('Erro de catálogo'))

    render(<CatalogBrowser system="loinc" label="LOINC" onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('Erro de catálogo')).toBeInTheDocument()
    })
  })

  it('re-fetches with the search term when the user types in the search box', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: CBO_ITEMS, count: 2 })
    mockApiFetch.mockResolvedValueOnce({ results: [CBO_ITEMS[0]], count: 1 })

    render(<CatalogBrowser system="cbo" label="CBO" onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('2231-05')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/Buscar/i), { target: { value: 'clínico' } })

    await waitFor(() => {
      const call = mockApiFetch.mock.calls.find(([url]) => String(url).includes('search=cl'))
      expect(call).toBeTruthy()
    })
  })

  it('calls onClose when the close button is clicked', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: CBO_ITEMS, count: 2 })
    const onClose = vi.fn()

    render(<CatalogBrowser system="cbo" label="CBO" onClose={onClose} />)

    await waitFor(() => {
      expect(screen.getByText('2231-05')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Fechar' }))
    expect(onClose).toHaveBeenCalled()
  })
})
