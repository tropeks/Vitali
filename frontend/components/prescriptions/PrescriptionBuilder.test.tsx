import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PrescriptionBuilder } from './PrescriptionBuilder'

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

vi.mock('./SafetyBadge', () => ({
  SafetyBadge: () => <span>Seguro</span>,
}))

const fetchMock = vi.fn()

function response(data: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(data),
    blob: () => Promise.resolve(new Blob(['pdf'])),
  })
}

const prescription = {
  id: 'rx-1',
  encounter: 'enc-1',
  status: 'draft',
  status_display: 'Rascunho',
  is_signed: false,
  signed_at: null,
  prescriber_name: 'Dra. Ana',
  notes: '',
  created_at: '2026-05-06T10:00:00.000Z',
  items: [
    {
      id: 'item-1',
      drug: 'drug-1',
      drug_name: 'Dipirona',
      drug_generic_name: 'Dipirona sódica',
      drug_is_controlled: false,
      generic_name: 'Dipirona sódica',
      quantity: '1.000',
      unit_of_measure: 'ampola',
      dosage_instructions: 'EV a cada 6h se dor ou febre',
      notes: '',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  global.fetch = fetchMock as unknown as typeof fetch
})

describe('PrescriptionBuilder', () => {
  it('renders the CPOE as a dense order surface', async () => {
    fetchMock.mockResolvedValueOnce(response({ results: [prescription] }))

    render(<PrescriptionBuilder encounterId="enc-1" />)

    await screen.findByText('Ordens médicas')

    expect(screen.getByText('Ordens ativas')).toBeInTheDocument()
    expect(screen.getAllByText('1').length).toBeGreaterThan(0)
    expect(screen.getByText('Dipirona')).toBeInTheDocument()
    expect(screen.getByText('EV a cada 6h se dor ou febre')).toBeInTheDocument()
    expect(screen.getByText('Seguro')).toBeInTheDocument()
  })

  it('creates a prescription from the empty CPOE state', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ results: [] }))
      .mockResolvedValueOnce(response({ ...prescription, items: [] }))

    render(<PrescriptionBuilder encounterId="enc-1" />)

    await screen.findByText('Nenhuma prescrição neste atendimento.')
    await userEvent.click(screen.getByRole('button', { name: /Criar prescrição/i }))

    await screen.findByText('Prescrição #1')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/prescriptions/', expect.objectContaining({
      method: 'POST',
    }))
  })

  it('fills the composer from a quick CPOE preset and medication search', async () => {
    fetchMock
      .mockResolvedValueOnce(response({ results: [{ ...prescription, items: [] }] }))
      .mockResolvedValueOnce(response({
        results: [
          {
            id: 'drug-1',
            name: 'Dipirona',
            generic_name: 'Dipirona sódica',
            is_controlled: false,
          },
        ],
      }))

    render(<PrescriptionBuilder encounterId="enc-1" />)

    await screen.findByText('Prescrição #1')
    await userEvent.click(screen.getByRole('button', { name: /Adicionar ordem/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Dor/febre' }))

    expect(screen.getByLabelText('Posologia')).toHaveValue('Dipirona 1g EV/VO a cada 6h se dor ou febre')
    await screen.findByText('Dipirona sódica')

    await userEvent.click(screen.getByText('Dipirona sódica'))
    expect(screen.getByLabelText('Medicamento')).toHaveValue('Dipirona')
  })

  it('shows a retryable error state when CPOE loading fails', async () => {
    fetchMock.mockResolvedValueOnce(response({ detail: 'Erro de API' }, false, 500))

    render(<PrescriptionBuilder encounterId="enc-1" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Erro de API')
    expect(screen.getByText('Nenhuma prescrição neste atendimento.')).toBeInTheDocument()
  })
})
