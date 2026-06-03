import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import RiscoEstoquePage from './page'

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

const riskResponse = {
  stockout_safety_enabled: true,
  alerts: [
    {
      id: 'alert-1',
      kind: 'stockout_risk',
      kind_display: 'Risco de ruptura',
      drug: 'drug-1',
      material: null,
      product_name: 'Dipirona 500mg',
      stock_item: null,
      predicted_date: '2026-06-15',
      days_to_stockout: '6.0',
      predicted_waste_qty: null,
      suggested_reorder_qty: '170.00',
      message: 'Risco de ruptura (ADVISE): saldo 30, consumo 5/dia.',
      severity: 'advise',
      status: 'open',
      created_at: '2026-06-03T10:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/pharmacy/stock-alerts/') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({ status: 'acknowledged', alert_id: 'alert-1' }),
        text: async () => '',
      } as Response)
    }
    if (url.includes('/api/v1/pharmacy/stock/risk/')) {
      return okJson(riskResponse)
    }
    return okJson({ alerts: [], stockout_safety_enabled: true })
  })
})

describe('RiscoEstoquePage', () => {
  it('lists predicted stockout alerts from StockRiskView', async () => {
    render(<RiscoEstoquePage />)

    await waitFor(() => {
      expect(screen.getByText('Dipirona 500mg')).toBeInTheDocument()
    })
    expect(screen.getByText('Risco de ruptura')).toBeInTheDocument()
    expect(screen.getByText('6.0')).toBeInTheDocument()
    expect(screen.getByText('170.00')).toBeInTheDocument()
  })

  it('acknowledges an alert by calling the ack endpoint and removes it from the list', async () => {
    render(<RiscoEstoquePage />)

    await waitFor(() => {
      expect(screen.getByText('Dipirona 500mg')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /reconhecer/i }))

    await waitFor(() => {
      const ackCall = mockFetch.mock.calls.find(
        (call: unknown[]) =>
          String(call[0]).includes('/api/v1/pharmacy/stock-alerts/alert-1/acknowledge/') &&
          (call[1] as RequestInit | undefined)?.method === 'POST',
      )
      expect(ackCall).toBeTruthy()
    })

    await waitFor(() => {
      expect(screen.queryByText('Dipirona 500mg')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Nenhum alerta de risco em aberto.')).toBeInTheDocument()
  })
})
