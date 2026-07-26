import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import LogisticaPage from './page'

// ─── Mocks ────────────────────────────────────────────────────────────────────

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
  ApiError: class ApiError extends Error {},
}))

// ─── Sample data ──────────────────────────────────────────────────────────────

const FACILITIES = [{ id: 'fac-1', name: 'Unidade Centro' }]
const MATERIALS = [
  { id: 'mat-1', name: 'Luva estéril' },
  { id: 'mat-2', name: 'Seringa 10ml' },
]
const WAREHOUSES = [{ id: 'wh-1', name: 'Almoxarifado Central' }]
const STOCK = [{ id: 'stk-1', material: 'mat-1', material_name: 'Luva estéril', warehouse: 'wh-1', quantity: '50' }]

const REQ_DRAFT = {
  id: 'req-1',
  requesting_facility: 'fac-1',
  status: 'draft',
  notes: '',
  items: [{ id: 'ri-1', material: 'mat-1', quantity: '10' }],
  created_at: '2026-07-20T10:00:00Z',
}
const REQ_SUBMITTED = { ...REQ_DRAFT, id: 'req-2', status: 'submitted' }
const REQ_APPROVED = { ...REQ_DRAFT, id: 'req-3', status: 'approved' }

const PICKED_LIST = {
  id: 'pl-1',
  requisition: 'req-3',
  status: 'picked',
  items: [{ id: 'pi-1', requisition_item: 'ri-1', material: 'mat-1', source_stock_item: 'stk-1', quantity: '10', picked_qty: '10', is_picked: true }],
}

const DISPATCH_PENDING = {
  id: 'disp-1',
  manifest_code: 'MNF-TEST-001',
  pick_list: 'pl-1',
  source_warehouse: 'wh-1',
  destination_warehouse: null,
  status: 'pending',
  items: [{ id: 'di-1', material: 'mat-1', source_stock_item: 'stk-1', quantity: '10', received_qty: null }],
}

// ─── Router mock ──────────────────────────────────────────────────────────────

interface Lists {
  requisitions?: any[]
  pickLists?: any[]
  dispatches?: any[]
  proofs?: any[]
  discrepancies?: any[]
}

function setupApi(lists: Lists = {}) {
  const state = {
    requisitions: lists.requisitions ?? [],
    pickLists: lists.pickLists ?? [],
    dispatches: lists.dispatches ?? [],
    proofs: lists.proofs ?? [],
    discrepancies: lists.discrepancies ?? [],
  }
  mockApiFetch.mockImplementation((url: string, options?: any) => {
    const method = options?.method ?? 'GET'
    if (method === 'GET') {
      if (url.includes('/organization/facilities/')) return Promise.resolve(FACILITIES)
      if (url.includes('/pharmacy/materials/')) return Promise.resolve(MATERIALS)
      if (url.includes('/pharmacy/warehouses/')) return Promise.resolve(WAREHOUSES)
      if (url.includes('/pharmacy/stock/items/')) return Promise.resolve(STOCK)
      if (url.includes('/supply-requisitions/')) return Promise.resolve(state.requisitions)
      if (url.includes('/pick-lists/')) return Promise.resolve(state.pickLists)
      if (url.includes('/dispatches/')) return Promise.resolve(state.dispatches)
      if (url.includes('/proof-of-deliveries/')) return Promise.resolve(state.proofs)
      if (url.includes('/dispatch-discrepancies/')) return Promise.resolve(state.discrepancies)
    }
    return Promise.resolve({})
  })
}

function postCall(matcher: (url: string) => boolean) {
  return mockApiFetch.mock.calls.find(
    ([url, options]) => options?.method === 'POST' && matcher(url)
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('LogisticaPage', () => {
  it('shows the empty requisições state by default', async () => {
    setupApi()
    render(<LogisticaPage />)
    expect(await screen.findByText('Nenhuma requisição ainda.')).toBeInTheDocument()
  })

  it('renders requisition rows with facility name and status badge', async () => {
    setupApi({ requisitions: [REQ_DRAFT] })
    render(<LogisticaPage />)
    await waitFor(() => expect(screen.getByText('Unidade Centro')).toBeInTheDocument())
    expect(screen.getByText('Rascunho')).toBeInTheDocument()
    expect(screen.getByText(/Luva estéril/)).toBeInTheDocument()
  })

  it('creates a requisition with the expected POST body', async () => {
    setupApi()
    render(<LogisticaPage />)
    await screen.findByText('Nenhuma requisição ainda.')

    fireEvent.click(screen.getByRole('button', { name: '+ Nova requisição' }))

    fireEvent.change(await screen.findByLabelText('Unidade solicitante *'), { target: { value: 'fac-1' } })
    fireEvent.change(screen.getByLabelText('Material do item 1'), { target: { value: 'mat-1' } })
    fireEvent.change(screen.getByLabelText('Quantidade do item 1'), { target: { value: '7' } })

    fireEvent.click(screen.getByRole('button', { name: 'Criar requisição' }))

    await waitFor(() => {
      expect(postCall((u) => u.endsWith('/supply-requisitions/'))).toBeTruthy()
    })
    const [, init] = postCall((u) => u.endsWith('/supply-requisitions/'))!
    expect(JSON.parse(init.body)).toEqual({
      requesting_facility: 'fac-1',
      notes: '',
      items: [{ material: 'mat-1', quantity: '7' }],
    })
  })

  it('submits a draft requisition via the submit action', async () => {
    setupApi({ requisitions: [REQ_DRAFT] })
    render(<LogisticaPage />)
    await screen.findByText('Unidade Centro')

    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))

    await waitFor(() => {
      expect(postCall((u) => u.endsWith('/supply-requisitions/req-1/submit/'))).toBeTruthy()
    })
  })

  it('approves a submitted requisition via the approve action', async () => {
    setupApi({ requisitions: [REQ_SUBMITTED] })
    render(<LogisticaPage />)
    await screen.findByText('Unidade Centro')

    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))

    await waitFor(() => {
      expect(postCall((u) => u.endsWith('/supply-requisitions/req-2/approve/'))).toBeTruthy()
    })
  })

  it('creates a pick list from an approved requisition', async () => {
    setupApi({ requisitions: [REQ_APPROVED] })
    render(<LogisticaPage />)
    await screen.findByText('Unidade Centro')

    fireEvent.click(screen.getByRole('button', { name: 'Criar separação' }))

    await waitFor(() => {
      const call = postCall((u) => u.endsWith('/pick-lists/'))
      expect(call).toBeTruthy()
      expect(JSON.parse(call![1].body)).toEqual({ requisition: 'req-3' })
    })
  })

  it('renders the separação empty state', async () => {
    setupApi()
    render(<LogisticaPage />)
    await screen.findByText('Nenhuma requisição ainda.')
    fireEvent.click(screen.getByRole('tab', { name: 'Separação' }))
    expect(await screen.findByText('Nenhuma lista de separação.')).toBeInTheDocument()
  })

  it('creates a dispatch with the expected POST body', async () => {
    setupApi({ pickLists: [PICKED_LIST] })
    render(<LogisticaPage />)
    await screen.findByText('Nenhuma requisição ainda.')

    fireEvent.click(screen.getByRole('tab', { name: 'Despachos' }))
    expect(await screen.findByText('Nenhum despacho ainda.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '+ Novo despacho' }))

    fireEvent.change(await screen.findByLabelText('Lista de separação *'), { target: { value: 'pl-1' } })
    fireEvent.change(screen.getByLabelText('Armazém de origem *'), { target: { value: 'wh-1' } })
    // manifest_code is auto-generated and shown prominently as the QR payload
    const manifestInput = screen.getByLabelText('Código do manifesto (QR) *') as HTMLInputElement
    expect(manifestInput.value).not.toBe('')

    fireEvent.click(screen.getByRole('button', { name: 'Criar despacho' }))

    await waitFor(() => {
      expect(postCall((u) => u.endsWith('/dispatches/'))).toBeTruthy()
    })
    const [, init] = postCall((u) => u.endsWith('/dispatches/'))!
    const body = JSON.parse(init.body)
    expect(body.pick_list).toBe('pl-1')
    expect(body.source_warehouse).toBe('wh-1')
    expect(body.manifest_code).toBeTruthy()
  })

  it('ships a pending dispatch via the ship action', async () => {
    setupApi({ dispatches: [DISPATCH_PENDING] })
    render(<LogisticaPage />)
    await screen.findByText('Nenhuma requisição ainda.')

    fireEvent.click(screen.getByRole('tab', { name: 'Despachos' }))
    const row = (await screen.findByText('MNF-TEST-001')).closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: /Enviar/ }))

    await waitFor(() => {
      expect(postCall((u) => u.endsWith('/dispatches/disp-1/ship/'))).toBeTruthy()
    })
  })

  it('shows an error state when a load fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<LogisticaPage />)
    expect(await screen.findByText('Erro ao carregar a logística.')).toBeInTheDocument()
  })
})
