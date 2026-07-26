import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LeaveDecideModal from './LeaveDecideModal'
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

const REQUEST = {
  id: 'lr-5',
  employee: 'emp-1',
  employee_name: 'Ana Souza',
  leave_type: 'ferias',
  leave_type_display: 'Férias',
  start_date: '2026-08-01',
  end_date: '2026-08-10',
  reason: 'Descanso',
  status: 'pending' as const,
  approval: null,
  requested_by: 'user-2',
  requested_by_name: 'Ana Souza',
  created_at: '2026-07-20T10:00:00Z',
  updated_at: '2026-07-20T10:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LeaveDecideModal', () => {
  it('renders nothing when there is no request', () => {
    const { container } = render(
      <LeaveDecideModal open request={null} onClose={() => {}} onDecided={() => {}} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('posts an approve decision with notes', async () => {
    mockApiFetch.mockResolvedValueOnce({ ...REQUEST, status: 'approved' })
    const onDecided = vi.fn()

    render(
      <LeaveDecideModal open request={REQUEST as any} onClose={() => {}} onDecided={onDecided} />
    )

    fireEvent.change(screen.getByLabelText(/Observaç/), { target: { value: 'Aprovado, ok' } })
    fireEvent.click(screen.getByRole('button', { name: /Aprovar/ }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/leave-requests/lr-5/decide/')
    expect(options?.method).toBe('POST')
    expect(JSON.parse(options?.body as string)).toEqual({
      approve: true,
      note: 'Aprovado, ok',
    })

    await waitFor(() => expect(onDecided).toHaveBeenCalled())
  })

  it('posts a reject decision', async () => {
    mockApiFetch.mockResolvedValueOnce({ ...REQUEST, status: 'rejected' })

    render(<LeaveDecideModal open request={REQUEST as any} onClose={() => {}} onDecided={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Rejeitar/ }))

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalled())

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/leave-requests/lr-5/decide/')
    expect(options?.method).toBe('POST')
    expect(JSON.parse(options?.body as string)).toMatchObject({ approve: false })
  })

  it('surfaces the self-approval-blocked server error', async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiError(403, { detail: 'Você não pode aprovar sua própria solicitação.' })
    )

    render(<LeaveDecideModal open request={REQUEST as any} onClose={() => {}} onDecided={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Aprovar/ }))

    await waitFor(() => {
      expect(screen.getByText(/não pode aprovar sua própria/i)).toBeInTheDocument()
    })
  })
})
