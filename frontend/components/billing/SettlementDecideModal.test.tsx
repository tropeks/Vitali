import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import SettlementDecideModal from './SettlementDecideModal'
import type { Settlement } from './SettlementRow'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
  ApiError: class ApiError extends Error {},
}))

const SETTLEMENT: Settlement = {
  id: 'set-1',
  professional: 'pro-1',
  professional_name: 'Dra. Ana Souza',
  competency: '2026-06',
  gross_amount: '10000.00',
  deductions: '500.00',
  net_amount: '9500.00',
  status: 'draft',
  calculated_at: null,
  paid_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SettlementDecideModal', () => {
  it('POSTs to the approve action with an empty body and reports the update', async () => {
    const onDone = vi.fn()
    mockApiFetch.mockResolvedValueOnce({ ...SETTLEMENT, status: 'approved' })

    render(
      <SettlementDecideModal
        settlement={SETTLEMENT}
        action="approve"
        onClose={vi.fn()}
        onDone={onDone}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }))

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))

    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/billing/settlements/set-1/approve/')
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ status: 'approved' }))
  })

  it('POSTs to the pay action with an empty body', async () => {
    const onDone = vi.fn()
    mockApiFetch.mockResolvedValueOnce({ ...SETTLEMENT, status: 'paid' })

    render(
      <SettlementDecideModal
        settlement={{ ...SETTLEMENT, id: 'set-9', status: 'approved' }}
        action="pay"
        onClose={vi.fn()}
        onDone={onDone}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar pagamento' }))

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))

    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/billing/settlements/set-9/pay/')
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  it('shows an inline error and does not call onDone when the action fails', async () => {
    const onDone = vi.fn()
    mockApiFetch.mockRejectedValueOnce(new Error('409'))

    render(
      <SettlementDecideModal
        settlement={SETTLEMENT}
        action="approve"
        onClose={vi.fn()}
        onDone={onDone}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar aprovação' }))

    await waitFor(() => {
      expect(
        screen.getByText('Não foi possível concluir a ação. Verifique as permissões e tente novamente.')
      ).toBeInTheDocument()
    })
    expect(onDone).not.toHaveBeenCalled()
  })
})
