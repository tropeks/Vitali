import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import InpatientFeePanel from './InpatientFeePanel'

const mockApiFetch = vi.fn()
const mockApiFetchWithStatus = vi.fn()

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
  return {
    apiFetch: (...args: any[]) => mockApiFetch(...args),
    apiFetchWithStatus: (...args: any[]) => mockApiFetchWithStatus(...args),
    ApiError,
  }
})

vi.mock('@/components/billing/TUSSCodeSearch', () => ({
  default: ({ value, onChange, disabled }: any) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange({ id: 501, code: '18010023', description: 'TAXA DE OXIGÊNIO, POR HORA' })}
    >
      {value ? `${value.code} — ${value.description}` : 'Selecionar TUSS mock'}
    </button>
  ),
}))

const ADMISSION = {
  id: 'adm-1',
  patient: 'patient-1',
  admitting_professional: 'prof-1',
  attending_professional: 'prof-2',
  current_bed: 'bed-1',
  admission_source: 'emergencia',
  admission_datetime: '2026-07-20T10:00:00Z',
  actual_discharge_datetime: null,
  disposition: null,
  status: 'admitted',
}

const FEE = {
  id: 'fee-1',
  admission: 'adm-1',
  service_date: '2026-08-17',
  tuss_code: 501,
  tuss_code_display: '18010023 — TAXA DE OXIGÊNIO, POR HORA',
  description: 'TAXA DE OXIGÊNIO, POR HORA',
  quantity: '6.50',
  unit: 'hora',
  category: 'gas_medicinal',
  notes: '',
  created_by: 'user-1',
  created_by_name: 'Enfermeira Ana',
  created_at: '2026-08-17T10:00:00Z',
  updated_at: '2026-08-17T10:00:00Z',
}

function mockAdmissionAndFees(fees: unknown[] = []) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/admissions/')) return Promise.resolve([ADMISSION])
    if (path.startsWith('/api/v1/billing/inpatient-fees/')) return Promise.resolve(fees)
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('InpatientFeePanel', () => {
  it('does not render the form when the user lacks billing permission', () => {
    render(<InpatientFeePanel patientId="patient-1" canManage={false} />)
    expect(screen.getByText('Sem acesso a taxas e gases medicinais')).toBeInTheDocument()
    expect(screen.queryByText('Lançar taxa / gás medicinal')).not.toBeInTheDocument()
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('renders the list of fees already launched on the admission', async () => {
    mockAdmissionAndFees([FEE])
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() => expect(screen.getByText(/TAXA DE OXIGÊNIO, POR HORA/)).toBeInTheDocument())
    expect(screen.getByText('Enfermeira Ana')).toBeInTheDocument()
    expect(screen.getByText('Taxas e gases medicinais lançados (1)')).toBeInTheDocument()
  })

  it('submits successfully (201), clears the form and refreshes the list', async () => {
    mockAdmissionAndFees([])
    mockApiFetchWithStatus.mockResolvedValueOnce({ data: FEE, status: 201 })
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() => expect(screen.getByText('Nenhuma taxa lançada nesta internação ainda.')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Selecionar TUSS mock'))
    fireEvent.change(screen.getByLabelText('Quantidade *'), { target: { value: '6.5' } })
    fireEvent.change(screen.getByLabelText('Categoria (TISS) *'), {
      target: { value: 'gas_medicinal' },
    })

    // After the create call resolves, refetch the list with the newly launched fee.
    mockApiFetch.mockImplementation((path: string) => {
      if (path.startsWith('/api/v1/admissions/')) return Promise.resolve([ADMISSION])
      if (path.startsWith('/api/v1/billing/inpatient-fees/')) return Promise.resolve([FEE])
      return Promise.reject(new Error(`unexpected path ${path}`))
    })

    fireEvent.click(screen.getByRole('button', { name: 'Lançar taxa' }))

    await waitFor(() => expect(mockApiFetchWithStatus).toHaveBeenCalledWith(
      '/api/v1/billing/inpatient-fees/',
      expect.objectContaining({ method: 'POST' }),
    ))
    const [, opts] = mockApiFetchWithStatus.mock.calls[0]
    const body = JSON.parse(opts.body)
    expect(body).toMatchObject({
      admission: 'adm-1',
      tuss_code: 501,
      quantity: '6.5',
      unit: 'unidade',
      category: 'gas_medicinal',
    })

    // Form resets after a fresh (201) create.
    await waitFor(() => expect(screen.getByText('Selecionar TUSS mock')).toBeInTheDocument())
    expect((screen.getByLabelText('Quantidade *') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('Categoria (TISS) *') as HTMLSelectElement).value).toBe('')
    expect(screen.queryByText(/já estava lançada/)).not.toBeInTheDocument()
  })

  it('blocks the launch until the taxa/gás category is chosen', async () => {
    // A API aceita category vazia, mas a tela não: uma única linha sem categoria
    // derruba o breakdown de <valorTotal> da guia INTEIRA (regra tudo-ou-nada em
    // xml_engine._resolve_valor_total). O custo de esquecer é invisível na tela e
    // caro no faturamento, então o gate é aqui.
    mockAdmissionAndFees([])
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() =>
      expect(screen.getByText('Nenhuma taxa lançada nesta internação ainda.')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByText('Selecionar TUSS mock'))
    fireEvent.change(screen.getByLabelText('Quantidade *'), { target: { value: '6.5' } })

    expect(screen.getByRole('button', { name: 'Lançar taxa' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Categoria (TISS) *'), { target: { value: 'taxa' } })

    expect(screen.getByRole('button', { name: 'Lançar taxa' })).not.toBeDisabled()
  })

  it('shows the category of each launched fee', async () => {
    mockAdmissionAndFees([FEE])
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    // Escopado à TABELA de propósito: o <option> do seletor tem o mesmo texto, e
    // um getByText solto passaria mesmo que a coluna não existisse.
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
    const linha = screen.getByRole('row', { name: /TAXA DE OXIGÊNIO/ })
    expect(within(linha).getByText('Gás medicinal')).toBeInTheDocument()
  })

  it('flags a fee launched before the category existed', async () => {
    // Lançamento anterior à Onda 4: sem categoria e sem backfill honesto. Fica
    // visível de propósito — enquanto houver um assim na internação, a guia sai
    // sem breakdown por categoria, e quem olha a lista precisa poder saber disso.
    mockAdmissionAndFees([{ ...FEE, id: 'fee-legacy', category: '' }])
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
    const linha = screen.getByRole('row', { name: /TAXA DE OXIGÊNIO/ })
    expect(within(linha).getByText('Sem categoria')).toBeInTheDocument()
    expect(within(linha).queryByText('Gás medicinal')).not.toBeInTheDocument()
  })

  it('surfaces the idempotent 200 as "already launched", not a new entry', async () => {
    mockAdmissionAndFees([])
    mockApiFetchWithStatus.mockResolvedValueOnce({ data: FEE, status: 200 })
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() => expect(screen.getByText('Nenhuma taxa lançada nesta internação ainda.')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Selecionar TUSS mock'))
    fireEvent.change(screen.getByLabelText('Quantidade *'), { target: { value: '6.5' } })
    fireEvent.change(screen.getByLabelText('Categoria (TISS) *'), { target: { value: 'taxa' } })
    fireEvent.click(screen.getByRole('button', { name: 'Lançar taxa' }))

    await waitFor(() => expect(screen.getByText(/já estava lançada/)).toBeInTheDocument())
    // The 200 path does NOT clear the selected TUSS — it was not a fresh submit.
    expect(screen.getByRole('button', { name: /18010023/ })).toBeInTheDocument()
  })

  it('shows a dict-shape 400 error on the matching field', async () => {
    mockAdmissionAndFees([])
    const { ApiError } = await import('@/lib/api')
    mockApiFetchWithStatus.mockRejectedValueOnce(
      new (ApiError as any)(400, { tuss_code: ['This field is required.'] }),
    )
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() => expect(screen.getByText('Nenhuma taxa lançada nesta internação ainda.')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Selecionar TUSS mock'))
    fireEvent.change(screen.getByLabelText('Quantidade *'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Categoria (TISS) *'), { target: { value: 'taxa' } })
    fireEvent.click(screen.getByRole('button', { name: 'Lançar taxa' }))

    await waitFor(() => expect(screen.getByText('This field is required.')).toBeInTheDocument())
  })

  it('shows a list-shape 400 error as a general message', async () => {
    mockAdmissionAndFees([])
    const { ApiError } = await import('@/lib/api')
    mockApiFetchWithStatus.mockRejectedValueOnce(
      new (ApiError as any)(400, [
        'TUSS 22010010 é da tabela 22; taxa de internação exige um código da tabela 18.',
      ]),
    )
    render(<InpatientFeePanel patientId="patient-1" canManage />)

    await waitFor(() => expect(screen.getByText('Nenhuma taxa lançada nesta internação ainda.')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Selecionar TUSS mock'))
    fireEvent.change(screen.getByLabelText('Quantidade *'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Categoria (TISS) *'), { target: { value: 'taxa' } })
    fireEvent.click(screen.getByRole('button', { name: 'Lançar taxa' }))

    await waitFor(() =>
      expect(
        screen.getByText(/exige um código da tabela 18/),
      ).toBeInTheDocument(),
    )
  })
})
