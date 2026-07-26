import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LeaveRequestForm from './LeaveRequestForm'
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
  fireEvent.change(screen.getByLabelText(/Funcionário/), { target: { value: 'emp-2' } })
  fireEvent.change(screen.getByLabelText(/Tipo/), { target: { value: 'licenca_medica' } })
  fireEvent.change(screen.getByLabelText(/Início/), { target: { value: '2026-09-01' } })
  fireEvent.change(screen.getByLabelText(/Fim/), { target: { value: '2026-09-05' } })
  fireEvent.change(screen.getByLabelText(/Motivo/), { target: { value: 'Consulta médica' } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LeaveRequestForm', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <LeaveRequestForm open={false} onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('submits a create POST with the correct body (no read-only fields)', async () => {
    mockApiFetch.mockResolvedValueOnce({ id: 'lr-9' })
    const onSuccess = vi.fn()

    render(<LeaveRequestForm open onClose={() => {}} onSuccess={onSuccess} employees={EMPLOYEES} />)

    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: /Solicitar/ }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/leave-requests/')
    expect(options?.method).toBe('POST')

    const body = JSON.parse(options?.body as string)
    expect(body).toEqual({
      employee: 'emp-2',
      leave_type: 'licenca_medica',
      start_date: '2026-09-01',
      end_date: '2026-09-05',
      reason: 'Consulta médica',
    })
    // never send server-set fields
    expect(body).not.toHaveProperty('status')
    expect(body).not.toHaveProperty('requested_by')
    expect(body).not.toHaveProperty('approval')

    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  it('surfaces a server validation error', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiError(400, { end_date: ['A data final deve ser após a inicial.'] })
    )

    render(<LeaveRequestForm open onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />)

    fillValidForm()
    fireEvent.change(screen.getByLabelText(/Fim/), { target: { value: '2026-08-01' } })
    fireEvent.click(screen.getByRole('button', { name: /Solicitar/ }))

    await waitFor(() => {
      expect(screen.getByText(/data final deve ser após/i)).toBeInTheDocument()
    })
  })
})
