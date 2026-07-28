import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AsoForm from './AsoForm'
import { apiFetch, ApiError } from '@/lib/api'

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

const EMPLOYEES = [
  { id: 'emp-1', full_name: 'Ana Souza' },
  { id: 'emp-2', full_name: 'Bruno Lima' },
]

function fillValidForm() {
  fireEvent.change(screen.getByLabelText(/Funcionário/), { target: { value: 'emp-1' } })
  fireEvent.change(screen.getByLabelText(/Tipo de exame/), { target: { value: 'periodic' } })
  fireEvent.change(screen.getByLabelText(/Data do exame/), { target: { value: '2026-07-20' } })
  fireEvent.change(screen.getByLabelText(/Vencimento/), { target: { value: '2027-07-20' } })
  fireEvent.change(screen.getByLabelText(/Resultado/), { target: { value: 'fit' } })
  fireEvent.change(screen.getByLabelText(/Médico/), { target: { value: 'Dr. Carlos Nunes' } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AsoForm', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <AsoForm open={false} onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('submits a create POST with the correct body (no read-only fields)', async () => {
    mockApiFetch.mockResolvedValueOnce({ id: 'aso-9' })
    const onSuccess = vi.fn()

    render(<AsoForm open onClose={() => {}} onSuccess={onSuccess} employees={EMPLOYEES} />)

    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: /Registrar ASO/ }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/occupational-health-exams/')
    expect(options?.method).toBe('POST')

    const body = JSON.parse(options?.body as string)
    expect(body).toEqual({
      employee: 'emp-1',
      exam_type: 'periodic',
      performed_on: '2026-07-20',
      expires_on: '2027-07-20',
      result: 'fit',
      provider_name: 'Dr. Carlos Nunes',
    })
    // never send server-set fields
    expect(body).not.toHaveProperty('id')
    expect(body).not.toHaveProperty('recorded_by')
    expect(body).not.toHaveProperty('created_at')
    expect(body).not.toHaveProperty('updated_at')

    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  it('defaults result to pending and omits optional empty fields', async () => {
    mockApiFetch.mockResolvedValueOnce({ id: 'aso-10' })

    render(<AsoForm open onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />)

    expect(screen.getByLabelText(/Resultado/)).toHaveValue('pending')

    fireEvent.change(screen.getByLabelText(/Funcionário/), { target: { value: 'emp-2' } })
    fireEvent.change(screen.getByLabelText(/Tipo de exame/), { target: { value: 'admission' } })
    fireEvent.change(screen.getByLabelText(/Data do exame/), { target: { value: '2026-07-01' } })
    fireEvent.change(screen.getByLabelText(/Médico/), { target: { value: 'Dra. Marta Reis' } })

    fireEvent.click(screen.getByRole('button', { name: /Registrar ASO/ }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())
    const [, options] = mockApiFetch.mock.calls[0]
    const body = JSON.parse(options?.body as string)
    expect(body).not.toHaveProperty('expires_on')
    expect(body).not.toHaveProperty('certificate_reference')
    expect(body).not.toHaveProperty('restrictions')
    expect(body.result).toBe('pending')
  })

  it('surfaces a server validation error', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiError(400, { expires_on: ['O vencimento deve ser após a data do exame.'] })
    )

    render(<AsoForm open onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />)

    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: /Registrar ASO/ }))

    await waitFor(() => {
      expect(screen.getByText(/vencimento deve ser após/i)).toBeInTheDocument()
    })
  })
})
