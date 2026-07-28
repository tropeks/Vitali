import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import AdmissionPanel from './AdmissionPanel'

const mockApiFetch = vi.fn()
vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number
    body: unknown
    constructor(status: number, body: unknown) {
      super(`API error ${status}`)
      this.status = status
      this.body = body
    }
  }
  return { apiFetch: (...args: any[]) => mockApiFetch(...args), ApiError }
})

const ADMISSION = {
  id: 'adm-1',
  patient: 'patient-1',
  admitting_professional: 'prof-1',
  attending_professional: 'prof-2',
  current_bed: 'bed-1',
  admission_source: 'emergencia',
  admission_datetime: '2026-07-20T10:00:00Z',
  actual_discharge_datetime: null,
  disposition: null,
  status: 'admitted',
}

const BOARD = {
  units: [
    {
      id: 'unit-1',
      code: 'U1',
      name: 'UTI Geral',
      rooms: [
        {
          id: 'room-1',
          name: '101',
          beds: [{ id: 'bed-1', identifier: 'L-01', status: 'ocupado', patient: null }],
        },
      ],
    },
  ],
}

const EVENTS = [
  {
    id: 'ev-1',
    admission: 'adm-1',
    event_type: 'admit',
    from_bed: null,
    to_bed: 'bed-1',
    reason: '',
    created_at: '2026-07-20T10:00:00Z',
  },
]

/** Route apiFetch by URL + method across all endpoints the panel touches. */
function routeApi(overrides: { admissions?: any; postDischarge?: () => any } = {}) {
  mockApiFetch.mockImplementation((url: string, opts?: any) => {
    if (url.includes('/discharge/') && opts?.method === 'POST') {
      return Promise.resolve(overrides.postDischarge ? overrides.postDischarge() : {})
    }
    if (url.startsWith('/api/v1/admissions/?patient=')) {
      return Promise.resolve(overrides.admissions ?? [ADMISSION])
    }
    if (url.startsWith('/api/v1/admission-events/')) {
      return Promise.resolve(EVENTS)
    }
    if (url === '/api/v1/beds/board/') {
      return Promise.resolve(BOARD)
    }
    if (url === '/api/v1/professionals/prof-1/') {
      return Promise.resolve({ id: 'prof-1', user_name: 'Dra. Carla' })
    }
    if (url === '/api/v1/professionals/prof-2/') {
      return Promise.resolve({ id: 'prof-2', user_name: 'Dr. João' })
    }
    return Promise.resolve([])
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AdmissionPanel', () => {
  it('hides everything without beds.read', () => {
    routeApi()
    render(
      <AdmissionPanel patientId="patient-1" canRead={false} canAdmit canDischarge />,
    )
    expect(screen.getByText('Sem acesso à internação')).toBeInTheDocument()
    // No fetch should even be attempted for a user without read access.
    expect(mockApiFetch).not.toHaveBeenCalled()
  })

  it('fetches the active stay scoped by patient + admitted status (read with beds.read)', async () => {
    routeApi()
    render(
      <AdmissionPanel patientId="patient-1" canRead canAdmit={false} canDischarge={false} />,
    )
    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/v1/admissions/?patient=patient-1&status=admitted',
      )
    })
  })

  it('renders the stay summary + ADT timeline for an admitted patient', async () => {
    routeApi()
    render(
      <AdmissionPanel patientId="patient-1" canRead canAdmit canDischarge />,
    )
    await waitFor(() => {
      expect(screen.getByText('Internação ativa')).toBeInTheDocument()
    })
    // Enriched bed identifier + unit name from /beds/board/.
    expect(screen.getByText(/L-01 — UTI Geral/)).toBeInTheDocument()
    // Responsável (attending) resolved from /professionals/.
    expect(screen.getByText('Dr. João')).toBeInTheDocument()
    // Source label from the enum map.
    expect(screen.getByText('Emergência')).toBeInTheDocument()
    // ADT timeline event.
    expect(screen.getByText('Admissão')).toBeInTheDocument()
  })

  it('shows the Admitir action when there is no active stay', async () => {
    routeApi({ admissions: [] })
    render(
      <AdmissionPanel patientId="patient-1" canRead canAdmit canDischarge />,
    )
    await waitFor(() => {
      expect(screen.getByText('Paciente não internado')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /Admitir paciente/ })).toBeInTheDocument()
  })

  it('hides the Admitir action without adt.admit', async () => {
    routeApi({ admissions: [] })
    render(
      <AdmissionPanel patientId="patient-1" canRead canAdmit={false} canDischarge />,
    )
    await waitFor(() => {
      expect(screen.getByText('Paciente não internado')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Admitir paciente/ })).not.toBeInTheDocument()
  })

  it('hides the Dar alta action without adt.discharge', async () => {
    routeApi()
    render(
      <AdmissionPanel patientId="patient-1" canRead canAdmit canDischarge={false} />,
    )
    await waitFor(() => {
      expect(screen.getByText('Internação ativa')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Dar alta/ })).not.toBeInTheDocument()
  })

  it('posts the chosen disposition on discharge', async () => {
    routeApi()
    render(
      <AdmissionPanel patientId="patient-1" canRead canAdmit canDischarge />,
    )
    await waitFor(() => {
      expect(screen.getByText('Internação ativa')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /Dar alta/ }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Desfecho' }), {
      target: { value: 'alta_a_pedido' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Confirmar alta/ }))

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find(
        ([url, opts]) => url === '/api/v1/admissions/adm-1/discharge/' && opts?.method === 'POST',
      )
      expect(postCall).toBeTruthy()
    })
    const postCall = mockApiFetch.mock.calls.find(
      ([url, opts]) => url === '/api/v1/admissions/adm-1/discharge/' && opts?.method === 'POST',
    )
    const body = JSON.parse(postCall![1].body)
    expect(body.disposition).toBe('alta_a_pedido')
  })

  it('reflects the ended stay after a successful discharge', async () => {
    // Admitted first; after discharge the reload returns no active stay.
    let discharged = false
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/discharge/') && opts?.method === 'POST') {
        discharged = true
        return Promise.resolve({})
      }
      if (url.startsWith('/api/v1/admissions/?patient=')) {
        return Promise.resolve(discharged ? [] : [ADMISSION])
      }
      if (url.startsWith('/api/v1/admission-events/')) return Promise.resolve(EVENTS)
      if (url === '/api/v1/beds/board/') return Promise.resolve(BOARD)
      if (url.startsWith('/api/v1/professionals/')) {
        return Promise.resolve({ id: 'prof', user_name: 'X' })
      }
      return Promise.resolve([])
    })

    render(<AdmissionPanel patientId="patient-1" canRead canAdmit canDischarge />)
    await waitFor(() => expect(screen.getByText('Internação ativa')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Dar alta/ }))
    fireEvent.click(screen.getByRole('button', { name: /Confirmar alta/ }))

    await waitFor(() => {
      expect(screen.getByText('Paciente não internado')).toBeInTheDocument()
    })
  })

  it('shows an error state when the active-stay fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<AdmissionPanel patientId="patient-1" canRead canAdmit canDischarge />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar internação')).toBeInTheDocument()
    })
  })
})
