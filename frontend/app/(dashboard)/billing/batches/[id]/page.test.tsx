import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BatchDetailPage from './page'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
  useParams: () => ({ id: 'batch-1' }),
}))

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

const mockFetch = vi.fn()
global.fetch = mockFetch

const openBatch = {
  id: 'batch-1',
  batch_number: 'LOTE-001',
  status: 'open',
  provider_name: 'Convênio X',
  guide_count: 1,
  total_value: '100.00',
  guides: [{ id: 'g-1', guide_number: 'GUIA-001', patient_name: 'Maria', total_value: '100.00', status: 'open' }],
}

const closedBatch = { ...openBatch, status: 'closed', closed_at: '2026-06-03T10:00:00Z' }

const glosaBlock = {
  code: 'glosa_safety_block',
  detail: 'Risco de glosa em uma ou mais guias. Reconheça os bloqueios antes de fechar.',
  guides: [
    {
      guide_id: 'g-1',
      guide_number: 'GUIA-001',
      alerts: [
        {
          id: 'alert-1',
          check_code: 'duplicate',
          severity: 'block',
          message: 'Procedimento já apresentado em outra guia ativa.',
          recommendation: 'Remova a duplicidade ou justifique.',
          guide_item: 'gi-1',
        },
      ],
    },
  ],
}

function okJson(data: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => data } as Response)
}

function statusJson(status: number, data: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BatchDetailPage glosa interception', () => {
  it('intercepts a glosa_safety_block 409, acknowledges per-guia, and retries close', async () => {
    const user = userEvent.setup()

    let closeAttempts = 0
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/v1/billing/batches/batch-1/') && init?.method !== 'POST') {
        return okJson(openBatch)
      }
      if (url.includes('/api/v1/billing/glosa-safety-alerts/alert-1/acknowledge/') && init?.method === 'POST') {
        return statusJson(204, {})
      }
      if (url.includes('/api/v1/billing/batches/batch-1/close/') && init?.method === 'POST') {
        closeAttempts += 1
        if (closeAttempts === 1) {
          return statusJson(409, glosaBlock)
        }
        return statusJson(200, closedBatch)
      }
      return okJson({})
    })

    render(<BatchDetailPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Fechar Lote' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Fechar Lote' }))

    // Interception modal opens instead of the generic error.
    expect(await screen.findByText('Risco de glosa')).toBeInTheDocument()
    expect(screen.getByText('Procedimento já apresentado em outra guia ativa.')).toBeInTheDocument()
    expect(screen.getByText('Risco alto')).toBeInTheDocument()

    // Enter a >=10-char justification and confirm.
    const textarea = screen.getByPlaceholderText('Descreva a justificativa do faturamento...')
    await user.type(textarea, 'Procedimento legítimo, coparticipação acordada com a operadora.')
    await user.click(screen.getByRole('button', { name: 'Reconhecer e fechar o lote' }))

    // After acknowledge + retry → success state.
    await waitFor(() => {
      expect(screen.getByText('Lote fechado com sucesso!')).toBeInTheDocument()
    })

    const ackCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).includes('/api/v1/billing/glosa-safety-alerts/alert-1/acknowledge/') &&
      (init as RequestInit | undefined)?.method === 'POST'
    ))
    expect(ackCall).toBeTruthy()
    expect(JSON.parse((ackCall![1] as RequestInit).body as string)).toMatchObject({
      reason: 'Procedimento legítimo, coparticipação acordada com a operadora.',
    })
    expect(closeAttempts).toBe(2)
  })

  it('refetches and shows a retry notice on batch_modified_during_close', async () => {
    const user = userEvent.setup()

    let batchFetches = 0
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/v1/billing/batches/batch-1/') && init?.method !== 'POST') {
        batchFetches += 1
        return okJson(openBatch)
      }
      if (url.includes('/api/v1/billing/batches/batch-1/close/') && init?.method === 'POST') {
        return statusJson(409, { code: 'batch_modified_during_close', detail: 'mudou' })
      }
      return okJson({})
    })

    render(<BatchDetailPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Fechar Lote' })).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Fechar Lote' }))

    await waitFor(() => {
      expect(screen.getByText(/O lote mudou; reavaliado/)).toBeInTheDocument()
    })
    // Initial load + one refetch after the modified-during-close 409.
    expect(batchFetches).toBe(2)
    // No glosa modal on this path.
    expect(screen.queryByText('Risco de glosa')).not.toBeInTheDocument()
  })
})
