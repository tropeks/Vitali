import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import DeliveryModal from './DeliveryModal'
import type { Dispatch } from './logisticsMeta'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
  ApiError: class ApiError extends Error {},
}))

const MATERIALS = [{ id: 'mat-1', name: 'Luva estéril' }]

const DISPATCH: Dispatch = {
  id: 'disp-1',
  manifest_code: 'MNF-TEST-001',
  pick_list: 'pl-1',
  source_warehouse: 'wh-1',
  destination_warehouse: null,
  status: 'in_transit',
  items: [{ id: 'di-1', material: 'mat-1', source_stock_item: 'stk-1', quantity: '10', received_qty: null }],
}

beforeEach(() => vi.clearAllMocks())

describe('DeliveryModal', () => {
  it('requires received_by before submitting', async () => {
    render(<DeliveryModal open dispatch={DISPATCH} materials={MATERIALS} onClose={vi.fn()} onDelivered={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar entrega' }))
    expect(await screen.findByText('Informe quem recebeu a entrega.')).toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('POSTs deliver with signature, GPS and a discrepancy', async () => {
    mockApiFetch.mockResolvedValueOnce({ id: 'pod-1' })
    const onDelivered = vi.fn()
    render(
      <DeliveryModal open dispatch={DISPATCH} materials={MATERIALS} onClose={vi.fn()} onDelivered={onDelivered} />
    )

    fireEvent.change(screen.getByLabelText('Recebido por *'), { target: { value: 'João Recebedor' } })
    fireEvent.change(screen.getByLabelText('Referência da assinatura (URL/ID)'), {
      target: { value: 'https://sig/abc' },
    })
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '-23.55' } })
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '-46.63' } })

    fireEvent.click(screen.getByRole('button', { name: /Adicionar divergência/ }))
    fireEvent.change(screen.getByLabelText('Tipo da divergência 1'), { target: { value: 'damaged' } })
    fireEvent.change(screen.getByLabelText('Item da divergência 1'), { target: { value: 'di-1' } })
    fireEvent.change(screen.getByLabelText('Quantidade da divergência 1'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Observação da divergência 1'), { target: { value: 'Caixa molhada' } })

    fireEvent.click(screen.getByRole('button', { name: 'Confirmar entrega' }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/concession/dispatches/disp-1/deliver/')
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body)
    expect(body.received_by).toBe('João Recebedor')
    expect(body.signature_ref).toBe('https://sig/abc')
    expect(body.geo_lat).toBe('-23.55')
    expect(body.geo_lng).toBe('-46.63')
    expect(body.discrepancies).toEqual([
      { type: 'damaged', dispatch_item: 'di-1', material: 'mat-1', quantity: '2', notes: 'Caixa molhada' },
    ])
    await waitFor(() => expect(onDelivered).toHaveBeenCalled())
  })
})
