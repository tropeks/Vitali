import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ControladosPage from './page'

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
  controlled_safety_enabled: true,
  alerts: [
    {
      id: 'alert-1',
      dispensation_id: 'disp-1',
      patient_id: 'pat-1',
      patient_name: 'Carlos Lima',
      drug: 'Clonazepam 2mg',
      drug_id: 'd-1',
      controlled_class: 'B1',
      signal_kind: 'refill_too_soon',
      signal_kind_display: 'Refill cedo demais',
      severity: 'advise',
      detail: { gap_days: 5 },
      status: 'open',
      engine_version: 'controlled-c1',
      acknowledged_by: null,
      acknowledged_at: null,
      note: '',
      created_at: '2026-06-04T10:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/pharmacy/controlled/alerts/alert-1/acknowledge/') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({ message: 'ok', alert_id: 'alert-1' }),
        text: async () => '',
      } as Response)
    }
    if (url.includes('/api/v1/pharmacy/controlled/alerts/')) {
      return okJson(response)
    }
    return okJson({ alerts: [], controlled_safety_enabled: true })
  })
})

describe('ControladosPage', () => {
  it('lists open controlled-diversion alerts', async () => {
    render(<ControladosPage />)
    await waitFor(() => {
      expect(screen.getByText('Carlos Lima')).toBeInTheDocument()
    })
    expect(screen.getByText('Clonazepam 2mg')).toBeInTheDocument()
    expect(screen.getByText('Refill cedo demais')).toBeInTheDocument()
  })

  it('acknowledges an alert and removes it', async () => {
    render(<ControladosPage />)
    await waitFor(() => {
      expect(screen.getByText('Carlos Lima')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /reconhecer/i }))
    await waitFor(() => {
      const ackCall = mockFetch.mock.calls.find(
        (call: unknown[]) =>
          String(call[0]).includes('/api/v1/pharmacy/controlled/alerts/alert-1/acknowledge/') &&
          (call[1] as RequestInit | undefined)?.method === 'POST',
      )
      expect(ackCall).toBeTruthy()
    })
    await waitFor(() => {
      expect(screen.queryByText('Carlos Lima')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Nenhum alerta de controlado em aberto.')).toBeInTheDocument()
  })

  it('shows disabled state when the flag is off', async () => {
    mockFetch.mockImplementation(() => okJson({ alerts: [], controlled_safety_enabled: false }))
    render(<ControladosPage />)
    await waitFor(() => {
      expect(screen.getByText(/monitoramento de diversão de controlados está desativado/i)).toBeInTheDocument()
    })
  })
})
