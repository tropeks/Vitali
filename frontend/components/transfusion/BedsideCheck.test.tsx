import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import BedsideCheck from './BedsideCheck'
import type { TransfusionRequest } from './transfusion-types'

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

const REQUEST: TransfusionRequest = {
  id: 'req-1',
  patient: 'patient-1',
  component: 1,
  component_display: 'Concentrado de hemácias',
  quantidade: 1,
  urgencia: 'urgencia',
  indicacao: 'Anemia sintomática',
  status: 'liberada',
  requester: 'user-1',
  crossmatches: [
    {
      id: 'cm-1',
      request: 'req-1',
      bag: 'bag-1',
      bag_identifier: 'DIN-0001',
      abo_compativel: true,
      rh_compativel: true,
      crossmatch_resultado: 'compativel',
      compativel: true,
    },
  ],
}

const BAG = {
  id: 'bag-1',
  identifier: 'DIN-0001',
  component: 1,
  component_display: 'Concentrado de hemácias',
  abo: 'O',
  rh_factor: 'positivo',
  volume_ml: 300,
  collection_date: '2026-07-01',
  expiry_date: '2026-08-01',
  serology_status: 'liberada',
  stock_status: 'disponivel',
  irradiada: false,
  leucodepletada: false,
  aferese: false,
  available: true,
}

const OK_ADMIN = {
  id: 'adm-1',
  request: 'req-1',
  bag: 'bag-1',
  bag_identifier: 'DIN-0001',
  patient: 'patient-1',
  status: 'em_andamento',
}

/** Routes blood-bags on mount + a queued sequence of `checar` responses. */
function routeApi(checar: Array<() => Promise<any>>, bags = [BAG]) {
  let call = 0
  mockApiFetch.mockImplementation((url: string) => {
    if (url === '/api/v1/blood-bags/') return Promise.resolve(bags)
    if (url.endsWith('/checar/')) {
      const next = checar[Math.min(call, checar.length - 1)]
      call += 1
      return next()
    }
    return Promise.resolve([])
  })
}

function checarCalls() {
  return mockApiFetch.mock.calls.filter(([url]) => String(url).endsWith('/checar/'))
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BedsideCheck', () => {
  it('picks the bolsa from stock and POSTs the checagem on 201 (happy path)', async () => {
    routeApi([() => Promise.resolve(OK_ADMIN)])
    const onChecked = vi.fn()
    render(
      <BedsideCheck
        request={REQUEST}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onChecked={onChecked}
      />,
    )

    // Bag auto-selected from stock (crossmatched bag preferred) → button enabled.
    const submit = await screen.findByRole('button', { name: 'Verificar e transfundir' })
    await waitFor(() => expect(submit).not.toBeDisabled())
    fireEvent.click(submit)

    await waitFor(() => expect(onChecked).toHaveBeenCalledWith(REQUEST, OK_ADMIN))

    const [url, options] = checarCalls()[0]
    expect(url).toBe('/api/v1/transfusion-requests/req-1/checar/')
    expect((options as RequestInit)?.method).toBe('POST')
    const body = JSON.parse((options as RequestInit)?.body as string)
    expect(body).toEqual({
      bag: 'bag-1',
      patient_barcode: 'MRN-001',
      bag_barcode: 'DIN-0001',
    })
  })

  it('on 422 shows the 5-certos breakdown with the failed certos and blocks (no record)', async () => {
    routeApi([
      () =>
        Promise.reject(
          new ApiError(422, {
            detail: 'Falha na checagem dos 5 certos. Informe override_reason para prosseguir.',
            checagem: {
              paciente: true,
              bolsa: false,
              componente: true,
              compatibilidade: false,
              validade: true,
              ok: false,
              mismatches: ['bolsa', 'compatibilidade'],
            },
          }),
        ),
    ])
    const onChecked = vi.fn()
    render(
      <BedsideCheck
        request={REQUEST}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onChecked={onChecked}
      />,
    )

    const submit = await screen.findByRole('button', { name: 'Verificar e transfundir' })
    await waitFor(() => expect(submit).not.toBeDisabled())
    fireEvent.click(submit)

    await waitFor(() => expect(screen.getAllByText('Falhou')).toHaveLength(2))
    expect(screen.getByTestId('certo-bolsa').className).toContain('border-red')
    expect(screen.getByTestId('certo-compatibilidade').className).toContain('border-red')

    expect(onChecked).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Justificativa do override')).toBeInTheDocument()
    expect(screen.getByLabelText('Segundo checador')).toBeInTheDocument()
  })

  it('override path: justification unblocks and re-POSTs with override_reason (+ witness) → 201', async () => {
    routeApi([
      () =>
        Promise.reject(
          new ApiError(422, {
            detail: 'Falha na checagem.',
            checagem: {
              paciente: true,
              bolsa: false,
              componente: true,
              compatibilidade: true,
              validade: true,
              ok: false,
              mismatches: ['bolsa'],
            },
          }),
        ),
      () => Promise.resolve(OK_ADMIN),
    ])
    const onChecked = vi.fn()
    render(
      <BedsideCheck
        request={REQUEST}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onChecked={onChecked}
      />,
    )

    const submit = await screen.findByRole('button', { name: 'Verificar e transfundir' })
    await waitFor(() => expect(submit).not.toBeDisabled())
    fireEvent.click(submit)

    const justification = await screen.findByLabelText('Justificativa do override')
    const proceed = screen.getByRole('button', { name: 'Transfundir com justificativa' })
    // Disabled until an override justification is supplied (witness is optional).
    expect(proceed).toBeDisabled()
    fireEvent.change(justification, { target: { value: 'DIN ilegível; conferido manualmente.' } })
    fireEvent.change(screen.getByLabelText('Segundo checador'), {
      target: { value: 'user-9' },
    })
    expect(proceed).not.toBeDisabled()

    fireEvent.click(proceed)
    await waitFor(() => expect(onChecked).toHaveBeenCalled())
    expect(checarCalls()).toHaveLength(2)
    const body = JSON.parse((checarCalls()[1][1] as RequestInit)?.body as string)
    expect(body.override_reason).toBe('DIN ilegível; conferido manualmente.')
    expect(body.witness).toBe('user-9')
    expect(body.bag).toBe('bag-1')
  })

  it('on 409 surfaces a "não liberada" error without recording', async () => {
    routeApi([() => Promise.reject(new ApiError(409, { detail: 'Bolsa não liberada.' }))])
    const onChecked = vi.fn()
    render(
      <BedsideCheck
        request={REQUEST}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onChecked={onChecked}
      />,
    )

    const submit = await screen.findByRole('button', { name: 'Verificar e transfundir' })
    await waitFor(() => expect(submit).not.toBeDisabled())
    fireEvent.click(submit)

    await waitFor(() => expect(screen.getByText(/não liberada/)).toBeInTheDocument())
    expect(onChecked).not.toHaveBeenCalled()
  })
})
