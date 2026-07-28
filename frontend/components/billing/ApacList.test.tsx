import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ApacList from './ApacList'
import type { ApacAutorizacaoLine } from './sus-types'

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

const APACS: ApacAutorizacaoLine[] = [
  {
    id: 1,
    competencia: 7,
    numero_apac: '2826000000001',
    validade_inicio: '2026-07-01',
    validade_fim: '2026-09-30',
    procedimento_principal: 99,
    cid_principal: 'C50',
    patient: 'p1',
    valor: '1200.00',
  },
]

function routeApi(overrides: { postApac?: () => any } = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url === '/api/v1/billing/apac-autorizacoes/' && opts?.method === 'POST') {
      return Promise.resolve(overrides.postApac ? overrides.postApac() : { id: 2 })
    }
    if (url.startsWith('/api/v1/sigtap/')) {
      return Promise.resolve([{ id: 99, code: '0304010', display: 'Quimioterapia' }])
    }
    if (url.startsWith('/api/v1/patients/')) {
      return Promise.resolve([{ id: 'p1', full_name: 'Maria Silva' }])
    }
    if (url.startsWith('/api/v1/professionals/')) {
      return Promise.resolve([{ id: 'prof-1', user_name: 'Dr. Ana' }])
    }
    return Promise.resolve([])
  })
}

async function pickCombobox(name: RegExp, optionText: RegExp) {
  const input = screen.getByRole('combobox', { name })
  fireEvent.focus(input)
  const option = await screen.findByRole('option', { name: optionText })
  fireEvent.click(option)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ApacList', () => {
  it('renders the APAC list', () => {
    routeApi()
    render(
      <ApacList competenciaId={7} apacs={APACS} canWrite aberta onChanged={vi.fn()} />,
    )
    expect(screen.getByText('2826000000001')).toBeInTheDocument()
    expect(screen.getByText('APAC (1)')).toBeInTheDocument()
  })

  it('hides "Nova APAC" without sus.write', () => {
    routeApi()
    render(
      <ApacList competenciaId={7} apacs={APACS} canWrite={false} aberta onChanged={vi.fn()} />,
    )
    expect(screen.queryByRole('button', { name: /Nova APAC/ })).not.toBeInTheDocument()
  })

  it('hides "Nova APAC" when the competência is not aberta', () => {
    routeApi()
    render(
      <ApacList competenciaId={7} apacs={APACS} canWrite aberta={false} onChanged={vi.fn()} />,
    )
    expect(screen.queryByRole('button', { name: /Nova APAC/ })).not.toBeInTheDocument()
  })

  it('creates an APAC through the form (POST payload) and reloads', async () => {
    routeApi()
    const onChanged = vi.fn()
    render(<ApacList competenciaId={7} apacs={[]} canWrite aberta onChanged={onChanged} />)

    fireEvent.click(screen.getByRole('button', { name: /Nova APAC/ }))
    fireEvent.change(screen.getByLabelText('Número da APAC'), {
      target: { value: '2826000000009' },
    })
    fireEvent.change(screen.getByLabelText('Início da validade'), {
      target: { value: '2026-07-01' },
    })
    fireEvent.change(screen.getByLabelText('Fim da validade'), {
      target: { value: '2026-09-30' },
    })
    fireEvent.change(screen.getByLabelText('Valor autorizado (R$)'), {
      target: { value: '1500' },
    })
    await pickCombobox(/Procedimento principal/, /0304010/)
    await pickCombobox(/^Paciente$/, /Maria Silva/)

    fireEvent.click(screen.getByRole('button', { name: /Criar APAC/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) =>
          url === '/api/v1/billing/apac-autorizacoes/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    const postCall = mockApiFetch.mock.calls.find(
      ([url, opts]) => url === '/api/v1/billing/apac-autorizacoes/' && opts?.method === 'POST',
    )
    const body = JSON.parse(postCall![1].body)
    expect(body.competencia).toBe(7)
    expect(body.numero_apac).toBe('2826000000009')
    expect(body.procedimento_principal).toBe(99)
    expect(body.patient).toBe('p1')
    expect(body.valor).toBe('1500')
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })
})
