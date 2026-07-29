import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import DonorPanel from './DonorPanel'

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

const DONORS = [
  {
    id: 'd1',
    full_name: 'João Doador',
    cpf: '123.456.789-00',
    abo: 'O',
    rh_factor: 'positivo',
    apto: true,
  },
  { id: 'd2', full_name: 'Ana Inapta', abo: '', rh_factor: '', apto: false },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockResolvedValue(DONORS)
})

describe('DonorPanel', () => {
  it('lists donors with blood type and aptidão', async () => {
    render(<DonorPanel canManage={false} />)
    await waitFor(() => expect(screen.getByText('João Doador')).toBeInTheDocument())
    expect(screen.getByText('O+')).toBeInTheDocument()
    expect(screen.getByText('Apto')).toBeInTheDocument()
    expect(screen.getByText('Inapto')).toBeInTheDocument()
  })

  it('hides Cadastrar doador without hemoterapia.manage', async () => {
    render(<DonorPanel canManage={false} />)
    await waitFor(() => expect(screen.getByText('João Doador')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Cadastrar doador/ })).not.toBeInTheDocument()
  })

  it('cadastra a donor with hemoterapia.manage', async () => {
    const created: string[] = []
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (opts?.method === 'POST') {
        created.push((opts as any).body)
        return Promise.resolve({ id: 'new' })
      }
      return Promise.resolve(DONORS)
    })
    render(<DonorPanel canManage />)
    await waitFor(() => expect(screen.getByText('João Doador')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Cadastrar doador/ }))
    const dialog = screen.getByRole('dialog', { name: 'Cadastrar doador' })

    fireEvent.change(within(dialog).getByLabelText('Nome completo'), {
      target: { value: 'Novo Doador' },
    })
    fireEvent.change(within(dialog).getByLabelText('Grupo ABO do doador'), {
      target: { value: 'A' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cadastrar doador' }))

    await waitFor(() => expect(created.length).toBe(1))
    expect(JSON.parse(created[0])).toMatchObject({ full_name: 'Novo Doador', abo: 'A', apto: true })
  })
})
