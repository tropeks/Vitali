import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import BcmaCheckModal from './BcmaCheckModal'
import type { MarDueItem } from './mar-types'

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

const ITEM: MarDueItem = {
  id: 'item-1',
  prescription: 'rx-1',
  drug_name: 'Dipirona',
  dose_amount: '500.0000',
  dose_unit: 'mg',
  route: 'oral',
  frequency_per_day: 4,
  dosage_instructions: '1 comprimido de 6/6h',
}

const RECORDED = {
  id: 'adm-1',
  status: 'given',
  bcma_verified: true,
}

function scanMedication(value = 'MED-XYZ') {
  fireEvent.change(screen.getByLabelText('Código do medicamento'), {
    target: { value },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('BcmaCheckModal', () => {
  it('POSTs the check and records the administration on 201 (happy path)', async () => {
    mockApiFetch.mockResolvedValueOnce(RECORDED)
    const onRecorded = vi.fn()
    render(
      <BcmaCheckModal
        item={ITEM}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onRecorded={onRecorded}
      />
    )

    scanMedication('MED-XYZ')
    fireEvent.click(screen.getByRole('button', { name: 'Verificar e administrar' }))

    await waitFor(() => expect(onRecorded).toHaveBeenCalledWith(ITEM, RECORDED))

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/emar/check/')
    expect((options as RequestInit)?.method).toBe('POST')
    const body = JSON.parse((options as RequestInit)?.body as string)
    expect(body).toEqual({
      prescription_item: 'item-1',
      patient_barcode: 'MRN-001',
      medication_barcode: 'MED-XYZ',
    })
  })

  it('on 422 shows the 5-certos breakdown with the failed rights and blocks (no record)', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiError(422, {
        detail: 'Falha na checagem dos 5 certos. Informe override_reason para prosseguir.',
        bcma: {
          patient: true,
          medication: false,
          dose: true,
          route: true,
          time: false,
          ok: false,
          mismatches: ['medication', 'time'],
        },
      })
    )
    const onRecorded = vi.fn()
    render(
      <BcmaCheckModal
        item={ITEM}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onRecorded={onRecorded}
      />
    )

    scanMedication('WRONG-MED')
    fireEvent.click(screen.getByRole('button', { name: 'Verificar e administrar' }))

    // Breakdown appears with two failed rights highlighted.
    await waitFor(() => expect(screen.getAllByText('Falhou')).toHaveLength(2))
    expect(screen.getByTestId('bcma-right-medication').className).toContain('border-red')
    expect(screen.getByTestId('bcma-right-time').className).toContain('border-red')

    // Blocked: nothing recorded, and an override justification is now required.
    expect(onRecorded).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Justificativa do override')).toBeInTheDocument()
  })

  it('override path: after a 422, a justification unblocks and re-POSTs with override_reason → 201', async () => {
    mockApiFetch
      .mockRejectedValueOnce(
        new ApiError(422, {
          detail: 'Falha na checagem dos 5 certos.',
          bcma: {
            patient: true,
            medication: false,
            dose: true,
            route: true,
            time: true,
            ok: false,
            mismatches: ['medication'],
          },
        })
      )
      .mockResolvedValueOnce({ ...RECORDED, bcma_verified: false })
    const onRecorded = vi.fn()
    render(
      <BcmaCheckModal
        item={ITEM}
        patientBarcode="MRN-001"
        onClose={vi.fn()}
        onRecorded={onRecorded}
      />
    )

    scanMedication('WRONG-MED')
    fireEvent.click(screen.getByRole('button', { name: 'Verificar e administrar' }))

    const justification = await screen.findByLabelText('Justificativa do override')
    // Proceed button is disabled until a justification is typed.
    const proceed = screen.getByRole('button', { name: 'Administrar com justificativa' })
    expect(proceed).toBeDisabled()

    fireEvent.change(justification, {
      target: { value: 'Código do fabricante ilegível; conferido manualmente.' },
    })
    expect(proceed).not.toBeDisabled()
    fireEvent.click(proceed)

    await waitFor(() => expect(onRecorded).toHaveBeenCalled())
    expect(mockApiFetch).toHaveBeenCalledTimes(2)
    const body = JSON.parse((mockApiFetch.mock.calls[1][1] as RequestInit)?.body as string)
    expect(body.override_reason).toBe('Código do fabricante ilegível; conferido manualmente.')
    expect(body.prescription_item).toBe('item-1')
  })
})
