import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AppointmentsPage from './page'

const push = vi.fn()
const mockApiFetch = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

vi.mock('@/components/appointments/AppointmentModal', () => ({
  default: ({ onCreated }: { onCreated: () => void }) => (
    <div role="dialog" aria-label="Novo agendamento">
      <button onClick={onCreated}>Criar agendamento</button>
    </div>
  ),
}))

vi.mock('@/components/appointments/PIXModal', () => ({
  default: ({ patientName }: { patientName: string }) => (
    <div role="dialog" aria-label="Cobrança PIX">PIX {patientName}</div>
  ),
}))

function makeAppointment(overrides: Partial<any> = {}) {
  return {
    id: 'appt-1',
    patient_name: 'Ana Lima',
    patient_mrn: 'PAC-001',
    professional: 'prof-1',
    professional_name: 'Dra. Carla Rocha',
    start_time: '2026-05-07T12:20:00-03:00',
    end_time: '2026-05-07T12:50:00-03:00',
    duration_minutes: 30,
    type: 'consultation',
    type_display: 'Consulta',
    status: 'confirmed',
    status_display: 'Confirmado',
    notes: '',
    whatsapp_reminder_sent: true,
    whatsapp_confirmed: false,
    arrived_at: null,
    started_at: null,
    ...overrides,
  }
}

function mockScheduleApi(appointments = [
  makeAppointment(),
  makeAppointment({
    id: 'appt-2',
    patient_name: 'Bruno Souza',
    patient_mrn: 'PAC-002',
    status: 'waiting',
    status_display: 'Aguardando',
    start_time: '2026-05-07T11:30:00-03:00',
    end_time: '2026-05-07T12:00:00-03:00',
    arrived_at: '2026-05-07T12:00:00-03:00',
  }),
  makeAppointment({
    id: 'appt-3',
    patient_name: 'Clara Nunes',
    patient_mrn: 'PAC-003',
    status: 'completed',
    status_display: 'Concluído',
    start_time: '2026-05-07T09:00:00-03:00',
    end_time: '2026-05-07T09:30:00-03:00',
    started_at: '2026-05-07T09:02:00-03:00',
  }),
]) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path.startsWith('/api/v1/professionals/')) {
      return Promise.resolve({
        results: [{ id: 'prof-1', user_name: 'Dra. Carla Rocha', specialty: 'Clínica médica' }],
      })
    }
    if (path === '/api/v1/appointments/today/') {
      return Promise.resolve(appointments)
    }
    if (path.startsWith('/api/v1/appointments/?')) {
      return Promise.resolve({ results: appointments })
    }
    if (path.endsWith('/check-in/')) {
      return Promise.resolve({ ...appointments[0], status: 'waiting', arrived_at: '2026-05-07T13:01:00-03:00' })
    }
    if (path.endsWith('/start/')) {
      const apptId = path.match(/appointments\/([^/]+)\/start/)?.[1] ?? 'unknown'
      return Promise.resolve({ ...appointments[0], encounter_id: `enc-${apptId}` })
    }
    if (path.endsWith('/status/')) {
      return Promise.resolve(appointments[0])
    }
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date('2026-05-07T13:00:00-03:00'))
  vi.clearAllMocks()
  mockScheduleApi()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AppointmentsPage', () => {
  it('renders the operational schedule cockpit with queue state and friction signals', async () => {
    render(<AppointmentsPage />)

    await waitFor(() => {
      expect(screen.getByText('Agenda Operacional')).toBeInTheDocument()
    })

    expect(screen.getByText('Fila assistencial de hoje')).toBeInTheDocument()
    expect(screen.getAllByText('Ana Lima').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Bruno Souza').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/min de espera/).length).toBeGreaterThan(0)
    expect(screen.getByText('Atritos do dia')).toBeInTheDocument()
    expect(screen.getByText('Grade semanal')).toBeInTheDocument()
  })

  it('uses the dedicated check-in endpoint from the queue', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AppointmentsPage />)

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /registrar chegada/i }).length).toBeGreaterThan(0)
    })

    const enabledCheckIn = screen
      .getAllByRole('button', { name: /registrar chegada/i })
      .find((button) => !button.hasAttribute('disabled'))
    expect(enabledCheckIn).toBeDefined()
    await user.click(enabledCheckIn!)

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/appointments/appt-1/check-in/', { method: 'POST' })
    })
  })

  it('starts the encounter directly from the queue without returning to the encounter list', async () => {
    mockScheduleApi([
      makeAppointment({
        id: 'appt-start',
        status: 'waiting',
        status_display: 'Aguardando',
        arrived_at: '2026-05-07T12:45:00-03:00',
      }),
    ])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<AppointmentsPage />)

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /iniciar atendimento/i }).length).toBeGreaterThan(0)
    })

    await user.click(screen.getAllByRole('button', { name: /iniciar atendimento/i })[0])

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/appointments/appt-start/start/', { method: 'POST' })
      expect(push).toHaveBeenCalledWith('/encounters/enc-appt-start')
    })
  })
})
