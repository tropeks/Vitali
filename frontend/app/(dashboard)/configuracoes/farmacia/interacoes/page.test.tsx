import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import InteracoesPage from './page'

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

const ALLERGEN_CLASS_ACTIVE = {
  id: 'ac-1',
  name: 'Penicilinas',
  members: 'amoxicilina, ampicilina',
  description: 'Beta-lactâmicos com anel penicilínico',
  active: true,
  source: 'ANVISA',
  version: '2024.1',
}

const ALLERGEN_CLASS_INACTIVE = {
  id: 'ac-2',
  name: 'Cefalosporinas',
  members: 'cefalexina, cefazolina',
  description: 'Beta-lactâmicos de primeira geração',
  active: false,
  source: 'ANVISA',
  version: '2024.1',
}

const DRUG_INTERACTION_ACTIVE = {
  id: 'di-1',
  ingredient_a: 'Varfarina',
  ingredient_b: 'Aspirina',
  severity: 'high',
  severity_display: 'Alta',
  active: true,
  source: 'DRUGBANK',
  version: '5.1',
}

const DRUG_INTERACTION_INACTIVE = {
  id: 'di-2',
  ingredient_a: 'Metformina',
  ingredient_b: 'Álcool',
  severity: 'moderate',
  severity_display: 'Moderada',
  active: false,
  source: 'DRUGBANK',
  version: '5.1',
}

// ─── Setup ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('InteracoesPage', () => {
  it('renders both tables with allergen and interaction data', async () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('allergen-classes')) {
        return Promise.resolve([ALLERGEN_CLASS_ACTIVE, ALLERGEN_CLASS_INACTIVE])
      }
      return Promise.resolve([DRUG_INTERACTION_ACTIVE, DRUG_INTERACTION_INACTIVE])
    })

    render(<InteracoesPage />)

    await waitFor(() => {
      expect(screen.getByText('Penicilinas')).toBeInTheDocument()
    })

    // Allergen class data
    expect(screen.getByText('Cefalosporinas')).toBeInTheDocument()
    expect(screen.getByText('amoxicilina, ampicilina')).toBeInTheDocument()
    expect(screen.getByText('Beta-lactâmicos com anel penicilínico')).toBeInTheDocument()

    // source/version visible
    const anvisaElements = screen.getAllByText(/ANVISA/)
    expect(anvisaElements.length).toBeGreaterThanOrEqual(1)

    // Drug interaction data
    expect(screen.getByText('Varfarina')).toBeInTheDocument()
    expect(screen.getByText('Aspirina')).toBeInTheDocument()
    expect(screen.getByText('Alta')).toBeInTheDocument()
    expect(screen.getByText('Metformina')).toBeInTheDocument()
    expect(screen.getByText('Moderada')).toBeInTheDocument()

    // active indicators
    const simElements = screen.getAllByText('Sim')
    expect(simElements.length).toBeGreaterThanOrEqual(2)
    const naoElements = screen.getAllByText('Não')
    expect(naoElements.length).toBeGreaterThanOrEqual(2)
  })

  it('clicking Desativar on an allergen class calls apiFetch with correct args and reloads', async () => {
    const user = userEvent.setup()

    // Initial load
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('allergen-classes')) {
        return Promise.resolve([ALLERGEN_CLASS_ACTIVE])
      }
      return Promise.resolve([DRUG_INTERACTION_ACTIVE])
    })

    render(<InteracoesPage />)

    await waitFor(() => {
      expect(screen.getByText('Penicilinas')).toBeInTheDocument()
    })

    // Clear and set up for toggle + reload
    mockApiFetch.mockClear()
    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path.includes('/set-active/')) {
        return Promise.resolve(undefined)
      }
      if (path.includes('allergen-classes')) {
        return Promise.resolve([ALLERGEN_CLASS_ACTIVE])
      }
      return Promise.resolve([DRUG_INTERACTION_ACTIVE])
    })

    // The active allergen has "Desativar" button
    const buttons = screen.getAllByRole('button', { name: 'Desativar' })
    // First Desativar button belongs to the allergen class (rendered first)
    await user.click(buttons[0])

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/allergen-classes/ac-1/set-active/',
        { method: 'POST', body: JSON.stringify({ active: false }) }
      )
    })

    // Reload happens (re-fetch allergen-classes)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/allergen-classes/'
      )
    })
  })

  it('clicking Desativar on a drug interaction calls apiFetch with correct args and reloads', async () => {
    const user = userEvent.setup()

    // Initial load
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('allergen-classes')) {
        return Promise.resolve([ALLERGEN_CLASS_INACTIVE])
      }
      return Promise.resolve([DRUG_INTERACTION_ACTIVE])
    })

    render(<InteracoesPage />)

    await waitFor(() => {
      expect(screen.getByText('Varfarina')).toBeInTheDocument()
    })

    // Clear and set up for toggle + reload
    mockApiFetch.mockClear()
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('/set-active/')) {
        return Promise.resolve(undefined)
      }
      if (path.includes('allergen-classes')) {
        return Promise.resolve([ALLERGEN_CLASS_INACTIVE])
      }
      return Promise.resolve([DRUG_INTERACTION_ACTIVE])
    })

    // ALLERGEN_CLASS_INACTIVE has "Ativar" button, DRUG_INTERACTION_ACTIVE has "Desativar"
    const desativarButton = screen.getByRole('button', { name: 'Desativar' })
    await user.click(desativarButton)

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/drug-interactions/di-1/set-active/',
        { method: 'POST', body: JSON.stringify({ active: false }) }
      )
    })

    // Reload happens (re-fetch drug-interactions)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/drug-interactions/'
      )
    })
  })

  it('clicking Ativar on an inactive row calls apiFetch with active:true', async () => {
    const user = userEvent.setup()

    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('allergen-classes')) {
        return Promise.resolve([ALLERGEN_CLASS_INACTIVE])
      }
      return Promise.resolve([DRUG_INTERACTION_INACTIVE])
    })

    render(<InteracoesPage />)

    await waitFor(() => {
      expect(screen.getByText('Cefalosporinas')).toBeInTheDocument()
    })

    mockApiFetch.mockClear()
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('/set-active/')) return Promise.resolve(undefined)
      if (path.includes('allergen-classes')) return Promise.resolve([ALLERGEN_CLASS_INACTIVE])
      return Promise.resolve([DRUG_INTERACTION_INACTIVE])
    })

    const ativarButtons = screen.getAllByRole('button', { name: 'Ativar' })
    await user.click(ativarButtons[0])

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/pharmacy/allergen-classes/ac-2/set-active/',
        { method: 'POST', body: JSON.stringify({ active: true }) }
      )
    })
  })

  it('renders empty state when both lists are empty', async () => {
    mockApiFetch.mockImplementation(() => Promise.resolve([]))

    render(<InteracoesPage />)

    await waitFor(() => {
      expect(screen.getByText('Nenhuma classe de reatividade cadastrada.')).toBeInTheDocument()
    })
    expect(screen.getByText('Nenhuma interação medicamentosa cadastrada.')).toBeInTheDocument()
  })

  it('renders error state when initial fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'))

    render(<InteracoesPage />)

    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar dados.')).toBeInTheDocument()
    })
  })
})
