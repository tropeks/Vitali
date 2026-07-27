import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import AdmitPatientModal from './AdmitPatientModal'
import { ApiError } from '@/lib/api'

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

const BEDS = [
  { id: 'bed-1', identifier: 'L-01', unit: 'unit-1', status: 'livre' },
  { id: 'bed-2', identifier: 'L-02', unit: 'unit-1', status: 'livre' },
]

const PROFESSIONALS = [
  { id: 'prof-1', user_name: 'Dra. Carla', council_number: 'CRM-1' },
  { id: 'prof-2', user_name: 'Dr. João', council_number: 'CRM-2' },
]

function routeApi(opts: { post?: () => any } = {}) {
  mockApiFetch.mockImplementation((url: string, init?: any) => {
    if (url.startsWith('/api/v1/admissions/') && init?.method === 'POST') {
      return opts.post ? opts.post() : Promise.resolve({ id: 'adm-new' })
    }
    if (url.startsWith('/api/v1/beds/')) {
      return Promise.resolve(BEDS)
    }
    if (url.startsWith('/api/v1/professionals/')) {
      return Promise.resolve({ results: PROFESSIONALS, next: null })
    }
    return Promise.resolve([])
  })
}

/** Pick a professional from a RemoteCombobox by its accessible label. */
async function pickProfessional(name: RegExp, optionText: RegExp) {
  fireEvent.change(screen.getByRole('combobox', { name }), { target: { value: 'dr' } })
  await vi.advanceTimersByTimeAsync(300)
  await vi.runAllTimersAsync()
  fireEvent.click(screen.getByRole('option', { name: optionText }))
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AdmitPatientModal', () => {
  it('loads free beds on mount (/beds/?status=livre)', async () => {
    vi.useFakeTimers()
    routeApi()
    render(<AdmitPatientModal patientId="patient-1" onClose={vi.fn()} onAdmitted={vi.fn()} />)
    expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/beds/?status=livre')
    // The livre beds populate the picker.
    await vi.waitFor(() =>
      expect(screen.getByRole('option', { name: 'L-01' })).toBeInTheDocument(),
    )
    vi.useRealTimers()
  })

  it('posts a new admission with the chosen professionals, source and bed', async () => {
    vi.useFakeTimers()
    const onAdmitted = vi.fn()
    const onClose = vi.fn()
    routeApi()
    render(
      <AdmitPatientModal patientId="patient-1" onClose={onClose} onAdmitted={onAdmitted} />,
    )
    await vi.runAllTimersAsync()

    await pickProfessional(/internador/, /Dra\. Carla/)
    await pickProfessional(/respons/, /Dr\. João/)
    fireEvent.change(screen.getByRole('combobox', { name: 'Origem da internação' }), {
      target: { value: 'centro_cirurgico' },
    })
    fireEvent.change(screen.getByRole('combobox', { name: 'Leito livre' }), {
      target: { value: 'bed-2' },
    })

    fireEvent.click(screen.getByRole('button', { name: /Confirmar internação/ }))
    await vi.runAllTimersAsync()

    const postCall = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/admissions/' && init?.method === 'POST',
    )
    expect(postCall).toBeTruthy()
    const body = JSON.parse(postCall![1].body)
    expect(body.patient).toBe('patient-1')
    expect(body.admitting_professional).toBe('prof-1')
    expect(body.attending_professional).toBe('prof-2')
    expect(body.bed).toBe('bed-2')
    expect(body.admission_source).toBe('centro_cirurgico')
    expect(typeof body.admission_datetime).toBe('string')
    expect(onAdmitted).toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('surfaces a 409 as "leito já ocupado" and does not close', async () => {
    vi.useFakeTimers()
    const onClose = vi.fn()
    routeApi({ post: () => Promise.reject(new ApiError(409, { detail: 'ocupado' })) })
    render(<AdmitPatientModal patientId="patient-1" onClose={onClose} onAdmitted={vi.fn()} />)
    await vi.runAllTimersAsync()

    await pickProfessional(/internador/, /Dra\. Carla/)
    await pickProfessional(/respons/, /Dr\. João/)
    fireEvent.change(screen.getByRole('combobox', { name: 'Leito livre' }), {
      target: { value: 'bed-1' },
    })

    fireEvent.click(screen.getByRole('button', { name: /Confirmar internação/ }))
    await vi.runAllTimersAsync()

    expect(screen.getByText(/Leito já ocupado/)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('validates that professionals and a bed are selected before posting', async () => {
    vi.useFakeTimers()
    routeApi()
    render(<AdmitPatientModal patientId="patient-1" onClose={vi.fn()} onAdmitted={vi.fn()} />)
    await vi.runAllTimersAsync()

    fireEvent.click(screen.getByRole('button', { name: /Confirmar internação/ }))
    await vi.runAllTimersAsync()

    expect(
      screen.getByText(/Selecione profissional internador, responsável e um leito livre/),
    ).toBeInTheDocument()
    const postCall = mockApiFetch.mock.calls.find(
      ([url, init]) => url === '/api/v1/admissions/' && init?.method === 'POST',
    )
    expect(postCall).toBeFalsy()
    vi.useRealTimers()
  })
})
