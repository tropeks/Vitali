import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch } from '@/lib/api'
import BloodBagEntryModal from './BloodBagEntryModal'

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

const COMPONENTS = [{ id: 7, code: 'CH', display: 'Concentrado de Hemácias' }]

beforeEach(() => {
  vi.clearAllMocks()
  mockApiFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/blood-components/')) return Promise.resolve(COMPONENTS)
    return Promise.resolve({ id: 'bag-new' })
  })
})

describe('BloodBagEntryModal', () => {
  it('validates required fields before posting', async () => {
    render(<BloodBagEntryModal onClose={() => {}} onCreated={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar bolsa' }))
    await waitFor(() =>
      expect(screen.getByText('Informe o identificador/DIN da bolsa.')).toBeInTheDocument()
    )
    expect(mockApiFetch.mock.calls.some(([u]) => u === '/api/v1/blood-bags/')).toBe(false)
  })

  it('posts a new bag with the chosen component + blood type', async () => {
    const onCreated = vi.fn()
    render(<BloodBagEntryModal onClose={() => {}} onCreated={onCreated} />)

    fireEvent.change(screen.getByLabelText('Identificador/DIN'), {
      target: { value: 'DIN-2026-1' },
    })
    // pick the component from the combobox
    fireEvent.focus(screen.getByPlaceholderText('Buscar hemocomponente...'))
    await waitFor(() =>
      expect(screen.getByText('CH — Concentrado de Hemácias')).toBeInTheDocument()
    )
    fireEvent.click(screen.getByText('CH — Concentrado de Hemácias'))

    fireEvent.change(screen.getByLabelText('Grupo ABO'), { target: { value: 'AB' } })
    fireEvent.change(screen.getByLabelText('Fator Rh'), { target: { value: 'negativo' } })
    fireEvent.change(screen.getByLabelText('Data de validade'), {
      target: { value: '2026-08-30' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar bolsa' }))

    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    const call = mockApiFetch.mock.calls.find(([u]) => u === '/api/v1/blood-bags/')
    expect(call).toBeTruthy()
    const body = JSON.parse((call![1] as any).body)
    expect(body).toMatchObject({
      identifier: 'DIN-2026-1',
      component: 7,
      abo: 'AB',
      rh_factor: 'negativo',
      expiry_date: '2026-08-30',
    })
  })

  it('surfaces a duplicate-DIN 400 error', async () => {
    const { ApiError } = await import('@/lib/api')
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/blood-components/')) return Promise.resolve(COMPONENTS)
      return Promise.reject(new ApiError(400, { detail: 'DIN já cadastrado.' }))
    })
    render(<BloodBagEntryModal onClose={() => {}} onCreated={() => {}} />)

    fireEvent.change(screen.getByLabelText('Identificador/DIN'), { target: { value: 'DUP' } })
    fireEvent.focus(screen.getByPlaceholderText('Buscar hemocomponente...'))
    await waitFor(() =>
      expect(screen.getByText('CH — Concentrado de Hemácias')).toBeInTheDocument()
    )
    fireEvent.click(screen.getByText('CH — Concentrado de Hemácias'))
    fireEvent.change(screen.getByLabelText('Data de validade'), {
      target: { value: '2026-08-30' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Cadastrar bolsa' }))

    await waitFor(() => expect(screen.getByText('DIN já cadastrado.')).toBeInTheDocument())
  })
})
