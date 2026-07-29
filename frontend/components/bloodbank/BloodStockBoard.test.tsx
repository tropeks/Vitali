import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import BloodStockBoard from './BloodStockBoard'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
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

const mockApiFetch = vi.mocked(apiFetch)

function bag(over: Partial<any> = {}) {
  return {
    id: 'b1',
    identifier: 'DIN-001',
    component: 7,
    component_display: 'Concentrado de Hemácias',
    abo: 'O',
    rh_factor: 'positivo',
    volume_ml: 300,
    collection_date: '2026-07-01',
    expiry_date: '2026-12-31',
    serology_status: 'liberada',
    stock_status: 'disponivel',
    irradiada: false,
    leucodepletada: false,
    aferese: false,
    available: true,
    ...over,
  }
}

const BAGS = [
  bag(),
  bag({
    id: 'b2',
    identifier: 'DIN-002',
    abo: 'A',
    rh_factor: 'negativo',
    serology_status: 'quarentena',
    stock_status: 'disponivel',
    available: false,
  }),
  bag({
    id: 'b3',
    identifier: 'DIN-003',
    stock_status: 'vencida',
    serology_status: 'liberada',
    expiry_date: '2020-01-01',
    available: false,
  }),
]

function stockCalls(): string[] {
  return mockApiFetch.mock.calls
    .map((c) => c[0] as string)
    .filter((u) => u.startsWith('/api/v1/blood-bags/'))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockResolvedValue(BAGS)
})

describe('BloodStockBoard', () => {
  it('renders bags with ABO/Rh, component and status', async () => {
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() => expect(screen.getByText('DIN-001')).toBeInTheDocument())

    expect(screen.getByLabelText('Bolsa DIN-001')).toBeInTheDocument()
    expect(screen.getAllByText('Concentrado de Hemácias').length).toBeGreaterThan(0)
    // ABO/Rh badge on the available O+ bag (also appears in the legend strip)
    expect(screen.getAllByText('O+').length).toBeGreaterThan(0)
    // status pills
    expect(screen.getAllByText('Disponível').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Em quarentena').length).toBeGreaterThan(0)
  })

  it('shows KPI counts (disponíveis, quarentena, vencidas)', async () => {
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() => expect(screen.getByText('DIN-001')).toBeInTheDocument())

    // 1 disponível (b1), 1 quarentena (b2), 1 vencida (b3)
    const kpis = screen.getByLabelText('Indicadores de estoque')
    const tileFor = (label: string) => within(kpis).getByText(label).closest('div')!.parentElement!
    expect(tileFor('Disponíveis')).toHaveTextContent('1')
    expect(tileFor('Em quarentena')).toHaveTextContent('1')
    expect(tileFor('Vencidas')).toHaveTextContent('1')
  })

  it('refetches with the stock_status filter param', async () => {
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() => expect(stockCalls().length).toBe(1))

    fireEvent.change(screen.getByLabelText('Filtrar por situação de estoque'), {
      target: { value: 'reservada' },
    })
    await waitFor(() => expect(stockCalls().length).toBe(2))
    expect(stockCalls().some((u) => u.includes('stock_status=reservada'))).toBe(true)
  })

  it('refetches with ABO + Rh filter params', async () => {
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() => expect(stockCalls().length).toBe(1))

    fireEvent.change(screen.getByLabelText('Filtrar por grupo ABO'), { target: { value: 'A' } })
    await waitFor(() => expect(stockCalls().some((u) => u.includes('abo=A'))).toBe(true))
    fireEvent.change(screen.getByLabelText('Filtrar por fator Rh'), {
      target: { value: 'negativo' },
    })
    await waitFor(() =>
      expect(stockCalls().some((u) => u.includes('rh_factor=negativo'))).toBe(true)
    )
  })

  it('hides Entrada de bolsa and the sorologia action without hemoterapia.manage', async () => {
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() => expect(screen.getByText('DIN-001')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Entrada de bolsa/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Registrar sorologia/ })).not.toBeInTheDocument()
  })

  it('opens the sorologia modal on a quarantined bag with hemoterapia.manage', async () => {
    render(<BloodStockBoard canManage />)
    await waitFor(() => expect(screen.getByText('DIN-002')).toBeInTheDocument())
    // Only the quarantined bag (b2) offers the action
    const buttons = screen.getAllByRole('button', { name: /Registrar sorologia/ })
    expect(buttons.length).toBe(1)
    fireEvent.click(buttons[0])
    expect(
      screen.getByRole('dialog', { name: 'Registrar triagem sorológica' })
    ).toBeInTheDocument()
  })

  it('opens the entrada modal with hemoterapia.manage', async () => {
    render(<BloodStockBoard canManage />)
    await waitFor(() => expect(screen.getByText('DIN-001')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Entrada de bolsa/ }))
    expect(
      screen.getByRole('dialog', { name: 'Cadastrar bolsa de sangue' })
    ).toBeInTheDocument()
  })

  it('shows an empty state when there are no bags', async () => {
    mockApiFetch.mockResolvedValue([])
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() =>
      expect(screen.getByText('Nenhuma bolsa no estoque')).toBeInTheDocument()
    )
  })

  it('shows an error state when the fetch fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<BloodStockBoard canManage={false} />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar o estoque')).toBeInTheDocument()
    )
  })
})
