/**
 * Vitest + @testing-library/react tests for AssignmentFormModal (Sprint A7-T2)
 *
 * Run: npx vitest run components/hr/AssignmentFormModal.test.tsx
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AssignmentFormModal from './AssignmentFormModal'

// ─── Mocks ────────────────────────────────────────────────────────────────────

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

vi.mock('@/lib/auth', () => ({
  getAccessToken: () => 'test-token',
}))

import { apiFetch } from '@/lib/api'
const mockApiFetch = vi.mocked(apiFetch)

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const EMPLOYEE_1 = { id: 'emp-1', full_name: 'Ana Souza' }
const UNIT_1 = { id: 'unit-1', name: 'Unidade Central' }
const POSITION_1 = { id: 'pos-1', title: 'Enfermeira' }

const DEFAULT_PROPS = {
  open: true,
  employees: [EMPLOYEE_1],
  units: [UNIT_1],
  positions: [POSITION_1],
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AssignmentFormModal', () => {
  it('does not render when open is false', () => {
    render(<AssignmentFormModal {...DEFAULT_PROPS} open={false} />)
    expect(screen.queryByText('Nova Lotação')).not.toBeInTheDocument()
  })

  it('renders required fields and dropdown options', () => {
    render(<AssignmentFormModal {...DEFAULT_PROPS} />)
    expect(screen.getByLabelText(/funcionário/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/unidade/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/cargo/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/data de início/i)).toBeInTheDocument()
    expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    expect(screen.getByText('Unidade Central')).toBeInTheDocument()
    expect(screen.getByText('Enfermeira')).toBeInTheDocument()
  })

  it('states the single-active-assignment invariant in the UI', () => {
    render(<AssignmentFormModal {...DEFAULT_PROPS} />)
    expect(
      screen.getByText(/encerra automaticamente a lotação ativa/i)
    ).toBeInTheDocument()
  })

  it('disables submit until required fields are filled', () => {
    render(<AssignmentFormModal {...DEFAULT_PROPS} />)
    expect(screen.getByRole('button', { name: /criar lotação/i })).toBeDisabled()
  })

  it('submits POST with correct body and omits read-only/server-managed fields', async () => {
    mockApiFetch.mockResolvedValueOnce({
      id: 'asg-1',
      employee: 'emp-1',
      unit: 'unit-1',
      cost_center: null,
      position: 'pos-1',
      role: '',
      start_date: '2026-02-01',
      end_date: null,
      active: true,
      created_at: '2026-02-01T00:00:00Z',
      updated_at: '2026-02-01T00:00:00Z',
    })

    render(<AssignmentFormModal {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByLabelText(/funcionário/i), { target: { value: 'emp-1' } })
    fireEvent.change(screen.getByLabelText(/unidade/i), { target: { value: 'unit-1' } })
    fireEvent.change(screen.getByLabelText(/cargo/i), { target: { value: 'pos-1' } })
    fireEvent.change(screen.getByLabelText(/data de início/i), {
      target: { value: '2026-02-01' },
    })

    const submitBtn = screen.getByRole('button', { name: /criar lotação/i })
    expect(submitBtn).not.toBeDisabled()
    fireEvent.click(submitBtn)

    await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1))

    const [url, options] = mockApiFetch.mock.calls[0]
    expect(url).toBe('/api/v1/hr/assignments/')
    expect(options?.method).toBe('POST')

    const body = JSON.parse(options?.body as string)
    expect(body).toMatchObject({
      employee: 'emp-1',
      unit: 'unit-1',
      position: 'pos-1',
      start_date: '2026-02-01',
    })
    // Server-managed / read-only fields must never be sent by the client.
    expect(body).not.toHaveProperty('active')
    expect(body).not.toHaveProperty('end_date')
    expect(body).not.toHaveProperty('id')
    expect(body).not.toHaveProperty('created_at')
    expect(body).not.toHaveProperty('updated_at')
  })

  it('calls onSuccess and closes after a successful create', async () => {
    const onSuccess = vi.fn()
    mockApiFetch.mockResolvedValueOnce({ id: 'asg-2' })
    render(<AssignmentFormModal {...DEFAULT_PROPS} onSuccess={onSuccess} />)

    fireEvent.change(screen.getByLabelText(/funcionário/i), { target: { value: 'emp-1' } })
    fireEvent.change(screen.getByLabelText(/unidade/i), { target: { value: 'unit-1' } })
    fireEvent.change(screen.getByLabelText(/data de início/i), {
      target: { value: '2026-02-01' },
    })
    fireEvent.click(screen.getByRole('button', { name: /criar lotação/i }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })

  it('shows an error message when the API call fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<AssignmentFormModal {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByLabelText(/funcionário/i), { target: { value: 'emp-1' } })
    fireEvent.change(screen.getByLabelText(/unidade/i), { target: { value: 'unit-1' } })
    fireEvent.change(screen.getByLabelText(/data de início/i), {
      target: { value: '2026-02-01' },
    })
    fireEvent.click(screen.getByRole('button', { name: /criar lotação/i }))

    await waitFor(() => {
      expect(screen.getByText('Erro inesperado. Tente novamente.')).toBeInTheDocument()
    })
  })
})
