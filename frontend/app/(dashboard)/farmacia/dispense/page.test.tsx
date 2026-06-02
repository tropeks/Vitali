import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DispensePage from './page'

vi.mock('next/navigation', () => ({
  useSearchParams: () => ({
    get: () => null,
  }),
}))

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

const mockFetch = vi.fn()
global.fetch = mockFetch

const signedPrescription = {
  id: 'rx-1',
  patient: 'p-1',
  patient_name: 'Maria Souza',
  patient_mrn: 'MRN-123',
  prescriber_name: 'Dra. Ana Lima',
  status: 'signed',
  status_display: 'Assinada',
  is_signed: true,
  created_at: '2026-05-07T08:00:00Z',
  items: [
    {
      id: 'item-1',
      drug: 'drug-1',
      drug_name: 'Amoxicilina',
      drug_generic_name: 'amoxicilina',
      drug_is_controlled: false,
      quantity: '5.000',
      unit_of_measure: 'un',
      dosage_instructions: 'Tomar 1 cápsula a cada 8 horas.',
    },
    {
      id: 'item-2',
      drug: 'drug-2',
      drug_name: 'Diazepam',
      drug_generic_name: 'diazepam',
      drug_is_controlled: true,
      quantity: '2.000',
      unit_of_measure: 'un',
      dosage_instructions: 'Tomar à noite.',
    },
  ],
}

function okJson(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: async () => data,
  } as Response)
}

function statusJson(status: number, data: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response)
}

const doseSafetyBlock = {
  code: 'dose_safety_block',
  detail: 'Dose fora do intervalo seguro. Reconheça os alertas com justificativa antes de prosseguir.',
  alerts: [
    {
      id: 'alert-1',
      prescription_item: 'item-1',
      alert_type: 'dose',
      severity: 'contraindication',
      status: 'flagged',
      message: 'Dose acima do intervalo seguro para o peso informado.',
      recommendation: 'Reveja a dose; confirme peso/idade ou ajuste para o intervalo esperado.',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/patients/?search=')) {
      return okJson({
        results: [
          {
            id: 'p-1',
            full_name: 'Maria Souza',
            medical_record_number: 'MRN-123',
            birth_date: '1990-01-01',
          },
        ],
      })
    }
    if (url.includes('/api/v1/prescriptions/?patient=p-1&status=signed')) {
      return okJson({ results: [signedPrescription] })
    }
    if (url.includes('/api/v1/prescriptions/?patient=p-1&status=partially_dispensed')) {
      return okJson({ results: [] })
    }
    if (url.includes('/api/v1/pharmacy/stock/availability/?drug=drug-1')) {
      return okJson({
        available_lots: [
          {
            id: 'lot-1',
            lot_number: 'A-001',
            expiry_date: '2026-06-01',
            quantity: '8.000',
            location: 'A1',
          },
        ],
        total: 8,
      })
    }
    if (url.includes('/api/v1/pharmacy/stock/availability/?drug=drug-2')) {
      return okJson({
        available_lots: [
          {
            id: 'lot-2',
            lot_number: 'C-001',
            expiry_date: '2026-06-01',
            quantity: '4.000',
            location: 'C1',
          },
        ],
        total: 4,
      })
    }
    if (url.includes('/api/v1/pharmacy/dispense/') && init?.method === 'POST') {
      return okJson({
        id: 'disp-1',
        total_quantity: '5.000',
        lots: [
          {
            stock_item: 'lot-1',
            lot_number: 'A-001',
            expiry_date: '2026-06-01',
            quantity: '5.000',
          },
        ],
      })
    }
    return okJson({ results: [] })
  })
})

async function selectPatientFromSearch() {
  fireEvent.change(screen.getByLabelText('Buscar paciente'), { target: { value: 'Maria' } })

  expect(await screen.findByText('Maria Souza')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /maria souza/i }))

  await waitFor(() => {
    expect(screen.getByText('Amoxicilina')).toBeInTheDocument()
  })
}

describe('DispensePage', () => {
  it('dispenses a signed prescription item with FEFO lot context', async () => {
    const user = userEvent.setup()
    render(<DispensePage />)

    await selectPatientFromSearch()
    await user.click(screen.getAllByRole('button', { name: 'Fechar item' })[0])

    await waitFor(() => {
      expect(screen.getByText(/A-001/)).toBeInTheDocument()
    })
    expect(screen.getByText('Pronta para dispensar')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Confirmar dispensação' }))

    await waitFor(() => {
      expect(screen.getByText('Dispensação registrada')).toBeInTheDocument()
    })

    const dispenseCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).includes('/api/v1/pharmacy/dispense/') && init?.method === 'POST'
    ))
    expect(dispenseCall).toBeTruthy()
    expect(JSON.parse(dispenseCall![1].body as string)).toMatchObject({
      prescription_item_id: 'item-1',
      quantity: 5,
      notes: '',
    })
  })

  it('blocks controlled medication dispensation without Portaria 344 notes', async () => {
    const user = userEvent.setup()
    render(<DispensePage />)

    await selectPatientFromSearch()
    await user.click(screen.getAllByRole('button', { name: 'Fechar item' })[1])

    await waitFor(() => {
      expect(screen.getByText('Registrar observação Portaria 344')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Confirmar dispensação' }))

    expect(await screen.findByText(/Pendências antes de dispensar/)).toHaveTextContent(
      'Registrar observação Portaria 344',
    )
    const dispenseCalls = mockFetch.mock.calls.filter(([url, init]) => (
      String(url).includes('/api/v1/pharmacy/dispense/') && init?.method === 'POST'
    ))
    expect(dispenseCalls).toHaveLength(0)
  })

  it('intercepts a dose_safety_block 409, acknowledges, and retries successfully', async () => {
    const user = userEvent.setup()

    // First dispense POST → 409 block; acknowledge → 204; second dispense POST → 201.
    let dispenseAttempts = 0
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/api/v1/patients/?search=')) {
        return okJson({
          results: [
            { id: 'p-1', full_name: 'Maria Souza', medical_record_number: 'MRN-123', birth_date: '1990-01-01' },
          ],
        })
      }
      if (url.includes('/api/v1/prescriptions/?patient=p-1&status=signed')) {
        return okJson({ results: [signedPrescription] })
      }
      if (url.includes('/api/v1/prescriptions/?patient=p-1&status=partially_dispensed')) {
        return okJson({ results: [] })
      }
      if (url.includes('/api/v1/pharmacy/stock/availability/?drug=drug-1')) {
        return okJson({
          available_lots: [
            { id: 'lot-1', lot_number: 'A-001', expiry_date: '2026-06-01', quantity: '8.000', location: 'A1' },
          ],
          total: 8,
        })
      }
      if (url.includes('/api/v1/safety-alerts/alert-1/acknowledge/') && init?.method === 'POST') {
        return statusJson(204, {})
      }
      if (url.includes('/api/v1/pharmacy/dispense/') && init?.method === 'POST') {
        dispenseAttempts += 1
        if (dispenseAttempts === 1) {
          return statusJson(409, doseSafetyBlock)
        }
        return statusJson(201, {
          id: 'disp-1',
          total_quantity: '5.000',
          lots: [{ stock_item: 'lot-1', lot_number: 'A-001', expiry_date: '2026-06-01', quantity: '5.000' }],
        })
      }
      return okJson({ results: [] })
    })

    render(<DispensePage />)

    await selectPatientFromSearch()
    await user.click(screen.getAllByRole('button', { name: 'Fechar item' })[0])

    await waitFor(() => {
      expect(screen.getByText(/A-001/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Confirmar dispensação' }))

    // The interception modal opens instead of the generic error.
    expect(await screen.findByText('Verificação de dose')).toBeInTheDocument()
    expect(screen.getByText('Dose acima do intervalo seguro para o peso informado.')).toBeInTheDocument()

    // Enter a >=10-char justification and confirm.
    const textarea = screen.getByPlaceholderText('Descreva a justificativa clínica...')
    await user.type(textarea, 'Paciente monitorizado em UTI, dose validada.')
    await user.click(screen.getByRole('button', { name: 'Reconhecer e dispensar' }))

    // After acknowledge + retry → success state.
    await waitFor(() => {
      expect(screen.getByText('Dispensação registrada')).toBeInTheDocument()
    })

    const ackCall = mockFetch.mock.calls.find(([url, init]) => (
      String(url).includes('/api/v1/safety-alerts/alert-1/acknowledge/') && init?.method === 'POST'
    ))
    expect(ackCall).toBeTruthy()
    expect(JSON.parse((ackCall![1] as RequestInit).body as string)).toMatchObject({
      reason: 'Paciente monitorizado em UTI, dose validada.',
    })
    expect(dispenseAttempts).toBe(2)
  })
})
