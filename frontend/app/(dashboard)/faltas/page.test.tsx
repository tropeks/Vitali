import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import FaltasPage from './page'

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

const mockFetch = vi.fn()
global.fetch = mockFetch as unknown as typeof fetch

function okJson(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response)
}

const response = {
  no_show_prediction_enabled: true,
  risks: [
    {
      id: 'risk-1',
      appointment_id: 'appt-1',
      patient_id: 'pat-1',
      patient_name: 'João Silva',
      appointment_start: '2026-06-10T14:00:00Z',
      appointment_type: 'return',
      appointment_type_display: 'Retorno',
      professional_name: 'Dra. Ana',
      score: '0.7200',
      band: 'high',
      band_display: 'Alto',
      breakdown: [],
      suggested_action: 'confirm_active',
      suggested_action_display: 'Confirmar ativamente',
      status: 'open',
      engine_version: 'noshow-n1',
      acknowledged_by: null,
      acknowledged_at: null,
      note: '',
      computed_at: '2026-06-04T03:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/no-show-risk/risk-1/acknowledge/') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({ message: 'ok', risk_id: 'risk-1' }),
        text: async () => '',
      } as Response)
    }
    if (url.includes('/api/v1/no-show-risk/')) {
      return okJson(response)
    }
    return okJson({ risks: [], no_show_prediction_enabled: true })
  })
})

describe('FaltasPage', () => {
  it('lists open no-show risks with band, score and suggested action', async () => {
    render(<FaltasPage />)
    await waitFor(() => {
      expect(screen.getByText('João Silva')).toBeInTheDocument()
    })
    // "Alto" appears both as a band filter button and the row badge.
    expect(screen.getAllByText('Alto').length).toBeGreaterThan(0)
    expect(screen.getByText('0.7200')).toBeInTheDocument()
    expect(screen.getByText('Confirmar ativamente')).toBeInTheDocument()
  })

  it('acknowledges a risk and removes it from the list', async () => {
    render(<FaltasPage />)
    await waitFor(() => {
      expect(screen.getByText('João Silva')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /reconhecer/i }))
    await waitFor(() => {
      const ackCall = mockFetch.mock.calls.find(
        (call: unknown[]) =>
          String(call[0]).includes('/api/v1/no-show-risk/risk-1/acknowledge/') &&
          (call[1] as RequestInit | undefined)?.method === 'POST',
      )
      expect(ackCall).toBeTruthy()
    })
    await waitFor(() => {
      expect(screen.queryByText('João Silva')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Nenhum risco de falta em aberto.')).toBeInTheDocument()
  })

  it('shows the disabled state when the flag is off', async () => {
    mockFetch.mockImplementation(() => okJson({ risks: [], no_show_prediction_enabled: false }))
    render(<FaltasPage />)
    await waitFor(() => {
      expect(screen.getByText(/predição de risco de falta está desativada/i)).toBeInTheDocument()
    })
  })
})
