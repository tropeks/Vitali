import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import WedgeTelemetryPage from './page'

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
  days: 30,
  wedges: [
    {
      key: 'no_show_prediction',
      enabled: true,
      alert_count: 4,
      acknowledged_count: 2,
      override_rate: 0.5,
      flywheel: {
        outcome_counts: { true_positive: 1, false_positive: 2 },
        graded_count: 3,
      },
      engine: 'deterministic',
    },
    {
      key: 'stockout_safety',
      enabled: false,
      alert_count: 1,
      acknowledged_count: 0,
      override_rate: 0,
      flywheel: { outcome_counts: {}, graded_count: 0 },
      engine: 'deterministic',
    },
    {
      key: 'deterioration_safety',
      enabled: true,
      alert_count: 0,
      acknowledged_count: 0,
      override_rate: null,
      flywheel: { outcome_counts: null, graded_count: 0 },
      engine: 'deterministic',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/wedge-telemetry/')) {
      return okJson(response)
    }
    return okJson({ days: 30, wedges: [] })
  })
})

describe('WedgeTelemetryPage', () => {
  it('renders the three wedge cards', async () => {
    render(<WedgeTelemetryPage />)
    await waitFor(() => {
      expect(screen.getByText('Risco de Falta')).toBeInTheDocument()
    })
    expect(screen.getByText('Risco de Ruptura')).toBeInTheDocument()
    expect(screen.getByText('Deterioração Clínica')).toBeInTheDocument()
  })

  it('shows the enabled badge state per wedge', async () => {
    render(<WedgeTelemetryPage />)
    await waitFor(() => {
      expect(screen.getByText('Risco de Falta')).toBeInTheDocument()
    })
    // 2 wedges enabled → 2 "Ativo" badges; 1 disabled → 1 "Inativo".
    expect(screen.getAllByText('Ativo')).toHaveLength(2)
    expect(screen.getAllByText('Inativo')).toHaveLength(1)
  })

  it('renders the override rate as a percentage', async () => {
    render(<WedgeTelemetryPage />)
    await waitFor(() => {
      expect(screen.getByText('Risco de Falta')).toBeInTheDocument()
    })
    // no_show override_rate 0.5 → 50%
    expect(screen.getByText('50%')).toBeInTheDocument()
    // deterioration override_rate null → em dash
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders flywheel outcome counts', async () => {
    render(<WedgeTelemetryPage />)
    await waitFor(() => {
      expect(screen.getByText('Risco de Falta')).toBeInTheDocument()
    })
    expect(screen.getByText('true_positive')).toBeInTheDocument()
    expect(screen.getByText('false_positive')).toBeInTheDocument()
  })
})
