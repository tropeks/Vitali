import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SusCompetenciaDetail from './SusCompetenciaDetail'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

const COMPETENCIA = { id: 7, establishment: 'f1', competencia: '2026-07', status: 'aberta' }
const BPA_I = [
  { id: 1, competencia: 7, sigtap: 10, patient: 'p1', quantidade: 1, valor: '10.00' },
  { id: 2, competencia: 7, sigtap: 11, patient: 'p2', quantidade: 1, valor: '10.00' },
]
const BPA_C = [{ id: 3, competencia: 7, sigtap: 12, cbo: 5, idade: 30, quantidade: 1, valor: '5.00' }]
const APACS = [
  {
    id: 4,
    competencia: 7,
    numero_apac: '2826000000001',
    situacao: 'solicitada',
    validade_inicio: '2026-07-01',
    validade_fim: '2026-09-30',
    procedimento_principal: 99,
    patient: 'p1',
    valor: '100.00',
  },
]
const AIHS = [
  {
    id: 5,
    competencia: 7,
    numero_aih: '2026070000001',
    situacao: 'solicitada',
    procedimento_principal: 99,
    patient: 'p1',
    data_internacao: '2026-07-01',
    data_saida: '2026-07-05',
    valor: '50.00',
  },
]

function routeApi(comp = COMPETENCIA) {
  mockApiFetch.mockImplementation((url: string) => {
    if (url === '/api/v1/billing/sus-competencias/7/') return Promise.resolve(comp)
    if (url.startsWith('/api/v1/billing/bpa-individualizado/')) return Promise.resolve(BPA_I)
    if (url.startsWith('/api/v1/billing/bpa-consolidado/')) return Promise.resolve(BPA_C)
    if (url.startsWith('/api/v1/billing/apac-autorizacoes/')) return Promise.resolve(APACS)
    if (url.startsWith('/api/v1/billing/aih-autorizacoes/')) return Promise.resolve(AIHS)
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SusCompetenciaDetail', () => {
  it('shows KPIs (counts + total valor) and the status badge', async () => {
    routeApi()
    render(
      <SusCompetenciaDetail competenciaId={7} canWrite canExport onBack={vi.fn()} />,
    )
    await waitFor(() =>
      expect(screen.getByText('Competência 2026-07')).toBeInTheDocument(),
    )
    // total valor = 10 + 10 + 5 + 100 (APAC) + 50 (AIH) = 175.00
    expect(screen.getByText(/175,00/)).toBeInTheDocument()
    expect(screen.getByText('Aberta')).toBeInTheDocument()
    // Section headings reflect the list counts.
    expect(screen.getByText('BPA-I — individualizado (2)')).toBeInTheDocument()
    expect(screen.getByText('BPA-C — consolidado (1)')).toBeInTheDocument()
    expect(screen.getByText('APAC (1)')).toBeInTheDocument()
    expect(screen.getByText('AIH — internação (1)')).toBeInTheDocument()
  })

  it('renders BPA-C manual entry form with sus.write on an aberta competência', async () => {
    routeApi()
    render(<SusCompetenciaDetail competenciaId={7} canWrite canExport onBack={vi.fn()} />)
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Adicionar BPA-C' })).toBeInTheDocument(),
    )
  })

  it('hides write surfaces without sus.write', async () => {
    routeApi()
    render(
      <SusCompetenciaDetail competenciaId={7} canWrite={false} canExport={false} onBack={vi.fn()} />,
    )
    await waitFor(() => expect(screen.getByText('Competência 2026-07')).toBeInTheDocument())
    expect(screen.queryByText('Adicionar BPA-C')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Gerar produção/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Nova APAC/ })).not.toBeInTheDocument()
  })

  it('shows an error state when the load fails', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    render(<SusCompetenciaDetail competenciaId={7} canWrite canExport onBack={vi.fn()} />)
    await waitFor(() =>
      expect(screen.getByText('Erro ao carregar competência')).toBeInTheDocument(),
    )
  })
})
