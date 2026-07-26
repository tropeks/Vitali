import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PickPanel from './PickPanel'
import type { PickList } from './logisticsMeta'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
  ApiError: class ApiError extends Error {},
}))

const MATERIALS = [{ id: 'mat-1', name: 'Luva estéril' }]
const WAREHOUSES = [{ id: 'wh-1', name: 'Almoxarifado Central' }]
const STOCK = [
  { id: 'stk-1', material: 'mat-1', material_name: 'Luva estéril', warehouse: 'wh-1', quantity: '50', lot_number: 'L1' },
]

const PICK_LIST: PickList = {
  id: 'pl-1',
  requisition: 'req-1',
  status: 'pending',
  items: [
    {
      id: 'pi-1',
      requisition_item: 'ri-1',
      material: 'mat-1',
      source_stock_item: null,
      quantity: '10',
      picked_qty: '0',
      is_picked: false,
    },
  ],
}

beforeEach(() => vi.clearAllMocks())

describe('PickPanel', () => {
  it('renders pick items with material name and status badge', () => {
    render(
      <PickPanel
        pickList={PICK_LIST}
        materials={MATERIALS}
        stockItems={STOCK}
        warehouses={WAREHOUSES}
        onPicked={vi.fn()}
      />
    )
    expect(screen.getByText('Luva estéril')).toBeInTheDocument()
    expect(screen.getByText('Pendente')).toBeInTheDocument()
  })

  it('POSTs the pick with pick_item, source_stock_item and picked_qty', async () => {
    mockApiFetch.mockResolvedValueOnce({ ...PICK_LIST, status: 'picked' })
    const onPicked = vi.fn()
    render(
      <PickPanel
        pickList={PICK_LIST}
        materials={MATERIALS}
        stockItems={STOCK}
        warehouses={WAREHOUSES}
        onPicked={onPicked}
      />
    )

    fireEvent.change(screen.getByLabelText('Estoque de origem'), { target: { value: 'stk-1' } })
    fireEvent.change(screen.getByLabelText('Qtd. separada'), { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: 'Separar' }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [url, init] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/concession/pick-lists/pl-1/pick/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      pick_item: 'pi-1',
      source_stock_item: 'stk-1',
      picked_qty: '10',
    })
    await waitFor(() => expect(onPicked).toHaveBeenCalled())
  })
})
