import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import NewPatientPage from './page'

const push = vi.fn()
const back = vi.fn()
const mockApiFetch = vi.fn()

vi.mock('next/navigation', () => ({ useRouter: () => ({ push, back }) }))
vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}))

beforeEach(() => vi.clearAllMocks())

describe('NewPatientPage', () => {
  it('organizes the complete registration in care-oriented sections', () => {
    render(<NewPatientPage />)

    expect(screen.getByText('Identificação')).toBeInTheDocument()
    expect(screen.getByText('Dados sociodemográficos')).toBeInTheDocument()
    expect(screen.getByText('Contato e endereço')).toBeInTheDocument()
    expect(screen.getByText('Emergência e acessibilidade')).toBeInTheDocument()
    expect(screen.getByLabelText('CNS (Cartão SUS)')).toBeInTheDocument()
    expect(screen.getByLabelText('Raça/cor (autodeclarada)')).toBeInTheDocument()
  })

  it('submits normalized identifiers and structured contact data', async () => {
    const user = userEvent.setup()
    mockApiFetch.mockResolvedValueOnce({ id: 'patient-1' })
    render(<NewPatientPage />)

    await user.type(screen.getByLabelText('Nome completo *'), 'Maria Silva')
    await user.type(screen.getByLabelText('CPF *'), '529.982.247-25')
    await user.type(screen.getByLabelText('Data de nascimento *'), '1990-05-20')
    await user.type(screen.getByLabelText('CNS (Cartão SUS)'), '123 4567 8901 2345')
    await user.type(screen.getByLabelText('Logradouro'), 'Rua das Flores')
    await user.type(screen.getByLabelText('CEP'), '01310-100')
    await user.type(screen.getByLabelText('Contato de emergência'), 'José Silva')
    await user.type(screen.getByLabelText('Mobilidade'), 'cadeira de rodas')
    await user.click(screen.getByRole('button', { name: 'Cadastrar paciente' }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1))
    const [url, options] = mockApiFetch.mock.calls[0]
    const payload = JSON.parse(options.body)
    expect(url).toBe('/api/v1/patients/')
    expect(payload.cpf).toBe('52998224725')
    expect(payload.cns).toBe('123456789012345')
    expect(payload.address).toMatchObject({ street: 'Rua das Flores', postal_code: '01310100' })
    expect(payload.emergency_contact.name).toBe('José Silva')
    expect(payload.accessibility_needs.mobility).toBe('cadeira de rodas')
    expect(payload).not.toHaveProperty('address_street')
    expect(push).toHaveBeenCalledWith('/patients/patient-1')
  })
})
