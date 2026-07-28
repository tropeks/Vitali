import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import ChecagemPage from './page'

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

const PATIENT = {
  id: 'pat-1',
  full_name: 'Maria Silva',
  medical_record_number: 'MRN-001',
}

const PRESCRIPTIONS = {
  results: [
    {
      id: 'rx-1',
      is_signed: true,
      status: 'signed',
      patient: 'pat-1',
      items: [
        {
          id: 'item-1',
          prescription: 'rx-1',
          drug_name: 'Dipirona',
          dose_amount: '500.0000',
          dose_unit: 'mg',
          route: 'oral',
          frequency_per_day: 4,
          dosage_instructions: '1 comprimido de 6/6h',
        },
      ],
    },
    {
      // draft prescriptions are NOT active orders → excluded from the MAR.
      id: 'rx-2',
      is_signed: false,
      status: 'draft',
      patient: 'pat-1',
      items: [
        {
          id: 'item-draft',
          prescription: 'rx-2',
          drug_name: 'Rascunho',
          dose_amount: '1.0000',
          dose_unit: 'mg',
          route: 'oral',
          frequency_per_day: 1,
          dosage_instructions: null,
        },
      ],
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

function scanPatient(value = 'MRN-001') {
  fireEvent.change(screen.getByLabelText('Código ou prontuário do paciente'), {
    target: { value },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Buscar paciente' }))
}

describe('ChecagemPage (MAR / checagem beira-leito)', () => {
  it('scans a patient, then lists only signed-order due medications', async () => {
    mockApiFetch
      .mockResolvedValueOnce({ results: [PATIENT] }) // patient search
      .mockResolvedValueOnce(PRESCRIPTIONS) // due meds

    render(<ChecagemPage />)
    scanPatient('MRN-001')

    await waitFor(() => expect(screen.getByText('Maria Silva')).toBeInTheDocument())
    expect(screen.getByText('Dipirona')).toBeInTheDocument()
    // draft order item is filtered out
    expect(screen.queryByText('Rascunho')).not.toBeInTheDocument()

    const [searchUrl] = mockApiFetch.mock.calls[0]
    expect(searchUrl).toContain('/api/v1/patients/')
    expect(searchUrl).toContain('search=MRN-001')
    const [rxUrl] = mockApiFetch.mock.calls[1]
    expect(rxUrl).toContain('/api/v1/prescriptions/')
    expect(rxUrl).toContain('patient=pat-1')
  })

  it('shows an empty state when the scanned patient has no active medications', async () => {
    mockApiFetch
      .mockResolvedValueOnce({ results: [PATIENT] })
      .mockResolvedValueOnce({ results: [] })

    render(<ChecagemPage />)
    scanPatient('MRN-001')

    await waitFor(() =>
      expect(screen.getByText(/Nenhuma medicação pendente/i)).toBeInTheDocument()
    )
  })

  it('shows a not-found state when no patient matches the scan', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: [] })

    render(<ChecagemPage />)
    scanPatient('NAO-EXISTE')

    await waitFor(() =>
      expect(screen.getByText(/Nenhum paciente encontrado/i)).toBeInTheDocument()
    )
  })

  it('runs a full BCMA check from the list and marks the item administered on 201', async () => {
    mockApiFetch
      .mockResolvedValueOnce({ results: [PATIENT] })
      .mockResolvedValueOnce(PRESCRIPTIONS)
      .mockResolvedValueOnce({ id: 'adm-1', status: 'given', bcma_verified: true })

    render(<ChecagemPage />)
    scanPatient('MRN-001')

    await waitFor(() => expect(screen.getByText('Dipirona')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Checar' }))

    fireEvent.change(await screen.findByLabelText('Código do medicamento'), {
      target: { value: 'MED-XYZ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verificar e administrar' }))

    await waitFor(() => expect(screen.getByText('Administrado')).toBeInTheDocument())

    const checkCall = mockApiFetch.mock.calls.find(([u]) => u === '/api/v1/emar/check/')
    expect(checkCall).toBeTruthy()
    const body = JSON.parse((checkCall![1] as RequestInit)?.body as string)
    expect(body.prescription_item).toBe('item-1')
    expect(body.patient_barcode).toBe('MRN-001')
  })
})
