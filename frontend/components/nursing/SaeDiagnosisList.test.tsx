import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import SaeDiagnosisList from './SaeDiagnosisList'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

const DIAG_ACTIVE = {
  id: 'diag-1',
  patient: 'patient-1',
  encounter: 'enc-1',
  nanda: 42,
  nanda_code: '00132',
  legacy_nanda_text: 'Dor aguda',
  nanda_unmatched: false,
  related_factors: 'Agente lesivo físico',
  defining_characteristics: 'Relato verbal de dor',
  status: 'active',
  priority: 'high',
  created_at: '2026-07-20T10:00:00Z',
}

const DIAG_RESOLVED = {
  id: 'diag-2',
  patient: 'patient-1',
  encounter: 'enc-1',
  nanda: null,
  nanda_code: '',
  legacy_nanda_text: 'Risco de queda',
  nanda_unmatched: true,
  related_factors: '',
  defining_characteristics: '',
  status: 'resolved',
  priority: 'low',
  created_at: '2026-07-18T10:00:00Z',
}

/** Route apiFetch by URL + method so the NANDA picker and the list coexist. */
function routeApi(overrides: Record<string, any> = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url.startsWith('/api/v1/nursing-diagnoses/') && opts?.method === 'POST') {
      return Promise.resolve(overrides.post ?? { id: 'diag-new' })
    }
    if (url.startsWith('/api/v1/nursing-diagnoses/')) {
      return Promise.resolve(overrides.list ?? [])
    }
    if (url.startsWith('/api/v1/terminology/nanda/')) {
      return Promise.resolve(overrides.nanda ?? { results: [], next: null })
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SaeDiagnosisList', () => {
  it('fetches nursing diagnoses scoped by patient', async () => {
    routeApi({ list: [] })
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/nursing-diagnoses/?patient=patient-1')
    })
  })

  it('shows an empty state when there are no diagnoses', async () => {
    routeApi({ list: [] })
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Sem diagnósticos de enfermagem')).toBeInTheDocument()
    })
  })

  it('renders diagnoses with NANDA code and status', async () => {
    routeApi({ list: [DIAG_ACTIVE, DIAG_RESOLVED] })
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Dor aguda')).toBeInTheDocument()
    })
    expect(screen.getByText('Risco de queda')).toBeInTheDocument()
    expect(screen.getByText(/00132/)).toBeInTheDocument()
    expect(screen.getByText('Ativo')).toBeInTheDocument()
    expect(screen.getByText('Resolvido')).toBeInTheDocument()
    // Unmatched NANDA is flagged.
    expect(screen.getByText('não reconciliado')).toBeInTheDocument()
  })

  it('handles the paginated {results,count} envelope', async () => {
    routeApi({ list: { count: 1, results: [DIAG_ACTIVE] } })
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Dor aguda')).toBeInTheDocument()
    })
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar diagnósticos')).toBeInTheDocument()
    })
  })

  it('hides the add control without sae.write', async () => {
    routeApi({ list: [] })
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite={false} />)
    await waitFor(() => {
      expect(screen.getByText('Sem diagnósticos de enfermagem')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Adicionar diagnóstico/ })).not.toBeInTheDocument()
  })

  it('posts a new diagnosis with nanda_code chosen from the NANDA picker', async () => {
    vi.useFakeTimers()
    routeApi({
      list: [],
      nanda: { results: [{ system: 'nanda', code: '00132', display: 'Dor aguda' }], next: null },
    })
    render(<SaeDiagnosisList patientId="patient-1" encounterId="enc-1" canWrite />)

    // Open the add form.
    await vi.waitFor(() =>
      expect(screen.getByRole('button', { name: /Adicionar diagnóstico/ })).toBeInTheDocument()
    )
    fireEvent.click(screen.getByRole('button', { name: /Adicionar diagnóstico/ }))

    // Pick a NANDA diagnosis from the terminology combobox.
    fireEvent.change(screen.getByRole('combobox', { name: /NANDA/ }), {
      target: { value: 'dor' },
    })
    await vi.advanceTimersByTimeAsync(300)
    await vi.runAllTimersAsync()
    fireEvent.click(screen.getByRole('option', { name: /Dor aguda/ }))

    // Submit.
    fireEvent.click(screen.getByRole('button', { name: /Salvar diagnóstico/ }))
    await vi.runAllTimersAsync()

    const postCall = mockApiFetch.mock.calls.find(
      ([url, opts]) => url === '/api/v1/nursing-diagnoses/' && opts?.method === 'POST'
    )
    expect(postCall).toBeTruthy()
    const body = JSON.parse(postCall![1].body)
    expect(body.nanda_code).toBe('00132')
    expect(body.encounter).toBe('enc-1')
    expect(body.status).toBe('active')
    vi.useRealTimers()
  })
})
