import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import TimeEntryForm from './TimeEntryForm'
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
  fireEvent.change(screen.getByLabelText(/Tipo de marcação/), { target: { value: 'out' } })
  fireEvent.change(screen.getByLabelText(/Data\/hora/), { target: { value: '2026-07-24T08:30' } })
  fireEvent.change(screen.getByLabelText(/Origem/), { target: { value: 'mobile' } })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TimeEntryForm', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <TimeEntryForm open={false} onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('submits a create POST with the correct body (no read-only fields)', async () => {
    mockApiFetch.mockResolvedValueOnce({ id: 'te-9' })
    const onSuccess = vi.fn()

    render(<TimeEntryForm open onClose={() => {}} onSuccess={onSuccess} employees={EMPLOYEES} />)

    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: /Registrar/ }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/time-entries/')
    expect(options?.method).toBe('POST')

    const body = JSON.parse(options?.body as string)
    expect(body.employee).toBe('emp-2')
    expect(body.event_type).toBe('out')
    expect(body.source).toBe('mobile')
    expect(body.occurred_at).toContain('2026-07-24')
    // never send server-set fields
    expect(body).not.toHaveProperty('id')
    expect(body).not.toHaveProperty('recorded_by')
    expect(body).not.toHaveProperty('created_at')

    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  it('defaults source to web and event type to in', () => {
    render(<TimeEntryForm open onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />)

    expect(screen.getByLabelText(/Tipo de marcação/)).toHaveValue('in')
    expect(screen.getByLabelText(/Origem/)).toHaveValue('web')
  })

  it('surfaces a server validation error', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiError(400, { occurred_at: ['Data/hora inválida.'] })
    )

    render(<TimeEntryForm open onClose={() => {}} onSuccess={() => {}} employees={EMPLOYEES} />)

    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: /Registrar/ }))

    await waitFor(() => {
      expect(screen.getByText(/Data\/hora inválida/i)).toBeInTheDocument()
    })
  })
})
