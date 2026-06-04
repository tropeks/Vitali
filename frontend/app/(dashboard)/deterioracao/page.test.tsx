import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import DeterioracaoPage from './page'

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
  deterioration_safety_enabled: true,
  alerts: [
    {
      id: 'alert-1',
      encounter_id: 'enc-1',
      patient_id: 'pat-1',
      patient_name: 'Maria Souza',
      vital_signs_id: 'vs-1',
      score: 7,
      band: 'high',
      band_display: 'Alto',
      breakdown: { respiratory_rate: 3, heart_rate: 2, temperature: 2 },
      any_param_three: true,
      spo2_scale: 1,
      severity: 'escalation',
      severity_display: 'Escalonamento (emergência)',
      status: 'open',
      message: 'NEWS2 7 — resposta de emergência.',
      engine_version: 'news2-rcp-2017-v1',
      acknowledged_by: null,
      acknowledged_at: null,
      note: '',
      created_at: '2026-06-04T10:00:00Z',
      updated_at: '2026-06-04T10:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/deterioration-alerts/alert-1/acknowledge/') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({ message: 'ok', alert_id: 'alert-1' }),
        text: async () => '',
      } as Response)
    }
    if (url.includes('/api/v1/deterioration-alerts/')) {
      return okJson(response)
    }
    return okJson({ alerts: [], deterioration_safety_enabled: true })
  })
})

describe('DeterioracaoPage', () => {
  it('lists open NEWS2 alerts with score, band and contributing params', async () => {
    render(<DeterioracaoPage />)

    await waitFor(() => {
      expect(screen.getByText('Maria Souza')).toBeInTheDocument()
    })
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('Alto')).toBeInTheDocument()
    // Contributing parameters rendered as chips (label + points).
    expect(screen.getByText('FR')).toBeInTheDocument()
    expect(screen.getByText('FC')).toBeInTheDocument()
  })

  it('acknowledges an alert via the ack endpoint and removes it from the list', async () => {
    render(<DeterioracaoPage />)

    await waitFor(() => {
      expect(screen.getByText('Maria Souza')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /reconhecer/i }))

    await waitFor(() => {
      const ackCall = mockFetch.mock.calls.find(
        (call: unknown[]) =>
          String(call[0]).includes('/api/v1/deterioration-alerts/alert-1/acknowledge/') &&
          (call[1] as RequestInit | undefined)?.method === 'POST',
      )
      expect(ackCall).toBeTruthy()
    })

    await waitFor(() => {
      expect(screen.queryByText('Maria Souza')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Nenhum alerta de deterioração em aberto.')).toBeInTheDocument()
  })

  it('shows the disabled state when the flag is off', async () => {
    mockFetch.mockImplementation(() => okJson({ alerts: [], deterioration_safety_enabled: false }))
    render(<DeterioracaoPage />)
    await waitFor(() => {
      expect(
        screen.getByText(/alerta de deterioração clínica está desativado/i),
      ).toBeInTheDocument()
    })
  })
})
