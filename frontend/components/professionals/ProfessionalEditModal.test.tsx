import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ProfessionalEditModal from './ProfessionalEditModal'
import type { Professional } from './ProfessionalRow'

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

const PROFESSIONAL: Professional = {
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
  cbo_unmatched: false,
  cnes_unmatched: false,
  is_active: true,
  created_at: '2024-01-15T10:00:00Z',
}

const CBO_RESULT = {
  system: 'cbo',
  code: '2231-05',
  display: 'Médico clínico',
  active: true,
  context: null,
}

const CNES_RESULT = {
  system: 'cnes',
  code: '1234567',
  display: 'Clínica Central',
  active: true,
  context: null,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ProfessionalEditModal', () => {
  it('search populates CBO options from the terminology endpoint', async () => {
    mockApiFetch.mockResolvedValue({ system: 'cbo', query: 'medico', count: 1, results: [CBO_RESULT] })

    render(<ProfessionalEditModal professional={PROFESSIONAL} onClose={vi.fn()} onSaved={vi.fn()} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'CBO' }), { target: { value: 'medico' } })

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/terminology/cbo/?q=medico&page_size=20')
    )
    expect(await screen.findByRole('option', { name: '2231-05 — Médico clínico' })).toBeInTheDocument()
  })

  it('search populates CNES options from the terminology endpoint', async () => {
    mockApiFetch.mockResolvedValue({ system: 'cnes', query: 'central', count: 1, results: [CNES_RESULT] })

    render(<ProfessionalEditModal professional={PROFESSIONAL} onClose={vi.fn()} onSaved={vi.fn()} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'CNES' }), { target: { value: 'central' } })

    await waitFor(() =>
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/terminology/cnes/?q=central&page_size=20')
    )
    expect(await screen.findByRole('option', { name: '1234567 — Clínica Central' })).toBeInTheDocument()
  })

  it('selecting CBO and CNES results sends cbo_code/cnes_code in the PATCH body', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('/terminology/cbo/')) {
        return Promise.resolve({ system: 'cbo', query: 'medico', count: 1, results: [CBO_RESULT] })
      }
      if (url.includes('/terminology/cnes/')) {
        return Promise.resolve({ system: 'cnes', query: 'central', count: 1, results: [CNES_RESULT] })
      }
      if (url.includes('/professionals/')) {
        return Promise.resolve({ ...PROFESSIONAL, cbo_code: CBO_RESULT.code, cnes_code: CNES_RESULT.code })
      }
      return Promise.reject(new Error(`unexpected url ${url}`))
    })

    const onSaved = vi.fn()
    render(<ProfessionalEditModal professional={PROFESSIONAL} onClose={vi.fn()} onSaved={onSaved} />)

    fireEvent.change(screen.getByRole('combobox', { name: 'CBO' }), { target: { value: 'medico' } })
    fireEvent.click(await screen.findByRole('option', { name: '2231-05 — Médico clínico' }))

    fireEvent.change(screen.getByRole('combobox', { name: 'CNES' }), { target: { value: 'central' } })
    fireEvent.click(await screen.findByRole('option', { name: '1234567 — Clínica Central' }))

    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(onSaved).toHaveBeenCalled())

    const patchCall = mockApiFetch.mock.calls.find(([url]) => url === '/api/v1/professionals/pro-1/')
    expect(patchCall).toBeTruthy()
    const [, init] = patchCall!
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({
      cbo_code: '2231-05',
      cnes_code: '1234567',
    })
  })

  it('cancel closes the modal without calling PATCH', () => {
    const onClose = vi.fn()
    render(<ProfessionalEditModal professional={PROFESSIONAL} onClose={onClose} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))

    expect(onClose).toHaveBeenCalled()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })
})
