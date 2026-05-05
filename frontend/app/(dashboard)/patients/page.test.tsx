import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PatientsPage from './page'

const push = vi.fn()
const mockApiFetch = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PatientsPage', () => {
  it('renders operational empty state with primary action', async () => {
    mockApiFetch.mockResolvedValueOnce({ results: [], count: 0 })

    render(<PatientsPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Nenhum paciente cadastrado ainda.').length).toBeGreaterThan(0)
    })

    expect(screen.getByText('Cadastre o primeiro paciente para liberar prontuário, agenda e faturamento.')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: /novo paciente/i })[0])
    expect(push).toHaveBeenCalledWith('/patients/new')
  })

  it('renders dense patient risk/status information', async () => {
    mockApiFetch.mockResolvedValueOnce({
      count: 2,
      results: [
        {
          id: 'p-1',
          full_name: 'Ana Lima',
          social_name: null,
          medical_record_number: 'MRN-001',
          birth_date: '1990-01-01',
          age: 36,
          phone: '11999999999',
          active_allergies_count: 2,
          is_active: true,
        },
        {
          id: 'p-2',
          full_name: 'Bruno Souza',
          medical_record_number: 'MRN-002',
          active_allergies_count: 0,
          is_active: false,
        },
      ],
    })

    render(<PatientsPage />)

    await waitFor(() => {
      expect(screen.getAllByText('Ana Lima').length).toBeGreaterThan(0)
    })

    expect(screen.getAllByText('MRN-001').length).toBeGreaterThan(0)
    expect(screen.getAllByText('2 alergias').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Inativo').length).toBeGreaterThan(0)
    expect(screen.getByText('Com alergia')).toBeInTheDocument()
  })
})
