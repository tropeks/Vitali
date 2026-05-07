import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import FarmaciaPage from './page'

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

const mockFetch = vi.fn()
global.fetch = mockFetch

function okJson(data: unknown) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/prescriptions/?status=signed')) {
      return okJson({
        results: [
          {
            id: 'rx-1',
            patient: 'p-1',
            patient_name: 'Maria Souza',
            patient_mrn: 'MRN-123',
            prescriber_name: 'Dra. Ana Lima',
            status: 'signed',
            status_display: 'Assinada',
            created_at: '2026-05-07T08:00:00Z',
            items: [
              {
                id: 'item-1',
                drug: 'drug-1',
                drug_name: 'Diazepam',
                drug_is_controlled: true,
                quantity: '2.000',
                unit_of_measure: 'un',
              },
            ],
          },
        ],
      })
    }
    if (url.includes('/api/v1/prescriptions/?status=partially_dispensed')) {
      return okJson({ results: [] })
    }
    if (url.includes('/api/v1/pharmacy/stock/items/')) {
      return okJson({
        results: [
          {
            id: 'stock-1',
            drug_name: 'Dipirona',
            material_name: null,
            lot_number: 'L-001',
            expiry_date: '2026-05-20',
            quantity: '3.000',
            min_stock: '5.000',
            location: 'A1',
            is_expired: false,
            is_low_stock: true,
          },
        ],
      })
    }
    if (url.includes('/api/v1/pharmacy/dispensations/')) {
      return okJson({
        results: [
          {
            id: 'disp-1',
            drug_name: 'Amoxicilina',
            total_quantity: '1.000',
            dispensed_by_name: 'Farmácia Central',
            dispensed_at: '2026-05-07T09:00:00Z',
            lots: [{ stock_item: 'stock-2', quantity: '1.000' }],
          },
        ],
      })
    }
    return okJson({ results: [] })
  })
})

describe('FarmaciaPage', () => {
  it('renders the pharmacy cockpit with queue, stock, and audit context', async () => {
    render(<FarmaciaPage />)

    expect(screen.getByText('Cockpit de Farmácia')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('Maria Souza')).toBeInTheDocument()
    })

    expect(screen.getByText('MRN-123')).toBeInTheDocument()
    expect(screen.getAllByText('1 controlado(s)').length).toBeGreaterThan(0)
    expect(screen.getByText('Dipirona')).toBeInTheDocument()
    expect(screen.getByText('Amoxicilina')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /dispensar/i })).toHaveAttribute(
      'href',
      '/farmacia/dispense?patient=p-1',
    )
  })
})
