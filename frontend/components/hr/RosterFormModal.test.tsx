import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import RosterFormModal from './RosterFormModal'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
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

beforeEach(() => {
  vi.clearAllMocks()
})

function facilitiesThenCreate() {
  mockApiFetch.mockImplementation((path: string, opts?: any) => {
    if (path === '/api/v1/organization/facilities/') {
      return Promise.resolve([{ id: 'f1', name: 'Unidade Centro' }])
    }
    if (path === '/api/v1/hr/duty-rosters/' && opts?.method === 'POST') {
      return Promise.resolve({ id: 'r-new', name: 'Escala UTI Agosto' })
    }
    return Promise.resolve([])
  })
}

describe('RosterFormModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <RosterFormModal open={false} onClose={() => {}} onSuccess={() => {}} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('loads facilities and POSTs the exact duty-roster body on create', async () => {
    facilitiesThenCreate()
    const onSuccess = vi.fn()

    render(<RosterFormModal open onClose={() => {}} onSuccess={onSuccess} />)

    // Facility option loaded from the API
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Unidade Centro' })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/Nome da escala/i), {
      target: { value: 'Escala UTI Agosto' },
    })
    fireEvent.change(screen.getByLabelText(/Unidade/i), { target: { value: 'f1' } })
    fireEvent.change(screen.getByLabelText(/Início/i), { target: { value: '2026-08-01' } })
    fireEvent.change(screen.getByLabelText(/Fim/i), { target: { value: '2026-08-31' } })

    fireEvent.click(screen.getByRole('button', { name: /Criar escala/i }))

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled()
    })

    const postCall = mockApiFetch.mock.calls.find(
      (c) => c[0] === '/api/v1/hr/duty-rosters/' && c[1]?.method === 'POST'
    )
    expect(postCall).toBeTruthy()
    expect(JSON.parse(postCall![1].body)).toEqual({
      name: 'Escala UTI Agosto',
      facility: 'f1',
      start_date: '2026-08-01',
      end_date: '2026-08-31',
      active: true,
    })
  })

  it('PUTs to the roster detail endpoint when editing', async () => {
    mockApiFetch.mockImplementation((path: string, opts?: any) => {
      if (path === '/api/v1/organization/facilities/') {
        return Promise.resolve([{ id: 'f1', name: 'Unidade Centro' }])
      }
      if (path === '/api/v1/hr/duty-rosters/r1/' && opts?.method === 'PUT') {
        return Promise.resolve({ id: 'r1' })
      }
      return Promise.resolve([])
    })

    render(
      <RosterFormModal
        open
        roster={{
          id: 'r1',
          name: 'Escala Antiga',
          facility: 'f1',
          start_date: '2026-08-01',
          end_date: '2026-08-31',
          active: true,
          created_at: '',
          updated_at: '',
        }}
        onClose={() => {}}
        onSuccess={() => {}}
      />
    )

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Unidade Centro' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Salvar/i }))

    await waitFor(() => {
      const putCall = mockApiFetch.mock.calls.find(
        (c) => c[0] === '/api/v1/hr/duty-rosters/r1/' && c[1]?.method === 'PUT'
      )
      expect(putCall).toBeTruthy()
    })
  })
})
