import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import AssetFormModal from './AssetFormModal'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
  ApiError: class ApiError extends Error {
    status: number
    body: any
    constructor(status: number, body: any, message?: string) {
      super(message ?? `API error ${status}`)
      this.status = status
      this.body = body
    }
  },
}))

const FACILITIES = [{ id: 'f1', name: 'Unidade Centro' }]

function mockFacilitiesThenWrite() {
  mockApiFetch.mockImplementation((path: string, opts?: any) => {
    if (path === '/api/v1/organization/facilities/') return Promise.resolve(FACILITIES)
    if (path === '/api/v1/concession/assets/' && opts?.method === 'POST')
      return Promise.resolve({ id: 'a-new' })
    if (path === '/api/v1/concession/assets/a1/' && opts?.method === 'PUT')
      return Promise.resolve({ id: 'a1' })
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AssetFormModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <AssetFormModal open={false} onClose={() => {}} onSuccess={() => {}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('POSTs the exact asset body on create', async () => {
    mockFacilitiesThenWrite()
    const onSuccess = vi.fn()

    render(<AssetFormModal open onClose={() => {}} onSuccess={onSuccess} />)

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Unidade Centro' })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Patrimônio/i), { target: { value: 'PAT-010' } })
    fireEvent.change(screen.getByLabelText(/^Nome/i), { target: { value: 'Tomógrafo' } })
    fireEvent.change(screen.getByLabelText(/^Modelo/i), { target: { value: 'Siemens' } })
    fireEvent.change(screen.getByLabelText(/Número de série/i), { target: { value: 'SN9' } })
    fireEvent.change(screen.getByLabelText(/Custo de aquisição/i), { target: { value: '500000.00' } })
    fireEvent.change(screen.getByLabelText(/Vida útil/i), { target: { value: '60' } })
    fireEvent.change(screen.getByLabelText(/Data de aquisição/i), { target: { value: '2025-01-01' } })

    fireEvent.click(screen.getByRole('button', { name: /Criar ativo/i }))

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled()
    })

    const postCall = mockApiFetch.mock.calls.find(
      (c) => c[0] === '/api/v1/concession/assets/' && c[1]?.method === 'POST'
    )
    expect(postCall).toBeTruthy()
    expect(JSON.parse(postCall![1].body)).toEqual({
      asset_tag: 'PAT-010',
      name: 'Tomógrafo',
      model: 'Siemens',
      serial_number: 'SN9',
      status: 'ACTIVE',
      ownership: 'OPERATOR',
      purchase_cost: '500000.00',
      useful_life_months: 60,
      purchase_date: '2025-01-01',
      current_location: null,
      active: true,
    })
  })

  it('PUTs to the asset detail endpoint when editing', async () => {
    mockFacilitiesThenWrite()

    render(
      <AssetFormModal
        open
        asset={{
          id: 'a1',
          asset_tag: 'PAT-001',
          name: 'Ultrassom',
          model: 'GE',
          serial_number: 'SN-1',
          status: 'ACTIVE',
          ownership: 'OPERATOR',
          purchase_cost: '120000.00',
          useful_life_months: 60,
          purchase_date: '2024-01-01',
          current_location: 'f1',
          active: true,
          monthly_depreciation: '2000.00',
        }}
        onClose={() => {}}
        onSuccess={() => {}}
      />
    )

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Unidade Centro' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Salvar/i }))

    await waitFor(() => {
      const putCall = mockApiFetch.mock.calls.find(
        (c) => c[0] === '/api/v1/concession/assets/a1/' && c[1]?.method === 'PUT'
      )
      expect(putCall).toBeTruthy()
    })
  })
})
