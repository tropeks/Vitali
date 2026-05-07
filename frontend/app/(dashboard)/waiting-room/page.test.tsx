import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import WaitingRoomPage from './page'

const push = vi.fn()
const mockApiFetch = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/lib/api', () => ({
  apiFetch: (...args: any[]) => mockApiFetch(...args),
}))

function makeAppointment(overrides: Partial<any> = {}) {
  return {
    id: 'appt-waiting-1',
    patient_name: 'Ana Lima',
    patient_mrn: 'PAC-001',
    professional_name: 'Dra. Carla Rocha',
    start_time: '2026-05-07T12:20:00-03:00',
    end_time: '2026-05-07T12:50:00-03:00',
    type_display: 'Consulta',
    status: 'scheduled',
    status_display: 'Agendado',
    duration_minutes: 30,
    arrived_at: null,
    ...overrides,
  }
}

function mockWaitingRoomApi(waiting = [
  makeAppointment(),
  makeAppointment({
    id: 'appt-waiting-2',
    patient_name: 'Bruno Souza',
    patient_mrn: 'PAC-002',
    status: 'waiting',
    status_display: 'Aguardando',
    start_time: '2026-05-07T12:40:00-03:00',
    end_time: '2026-05-07T13:10:00-03:00',
    arrived_at: '2026-05-07T12:35:00-03:00',
  }),
]) {
  mockApiFetch.mockImplementation((path: string) => {
    if (path === '/api/v1/waiting-room/') return Promise.resolve(waiting)
    if (path === '/api/v1/appointments/today/') {
      return Promise.resolve([
        ...waiting,
        makeAppointment({
          id: 'appt-progress',
          patient_name: 'Clara Nunes',
          status: 'in_progress',
          status_display: 'Em atendimento',
        }),
        makeAppointment({
          id: 'appt-done',
          patient_name: 'Diego Reis',
          status: 'completed',
          status_display: 'Concluído',
        }),
      ])
    }
    if (path.endsWith('/check-in/')) {
      return Promise.resolve({ ...waiting[0], status: 'waiting', arrived_at: '2026-05-07T13:00:00-03:00' })
    }
    if (path.endsWith('/start/')) {
      const apptId = path.match(/appointments\/([^/]+)\/start/)?.[1] ?? 'unknown'
      return Promise.resolve({ ...waiting[0], encounter_id: `enc-${apptId}` })
    }
    if (path.endsWith('/status/')) return Promise.resolve(waiting[0])
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date('2026-05-07T13:00:00-03:00'))
  vi.clearAllMocks()
  mockWaitingRoomApi()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('WaitingRoomPage', () => {
  it('renders operational queue context and links back to the schedule cockpit', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<WaitingRoomPage />)

    await waitFor(() => {
      expect(screen.getByText('Sala de Espera Operacional')).toBeInTheDocument()
    })

    expect(screen.getAllByText('Ana Lima').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Bruno Souza').length).toBeGreaterThan(0)
    expect(screen.getByText('Próximo paciente')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /agenda/i }))
    expect(push).toHaveBeenCalledWith('/appointments')
  })

  it('uses check-in and start actions without leaving the queue first', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<WaitingRoomPage />)

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /chegou/i }).length).toBeGreaterThan(0)
    })

    const enabledCheckIn = screen
      .getAllByRole('button', { name: /chegou/i })
      .find((button) => !button.hasAttribute('disabled'))
    expect(enabledCheckIn).toBeDefined()
    await user.click(enabledCheckIn!)

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/appointments/appt-waiting-1/check-in/', {
        method: 'POST',
      })
    })

    await user.click(screen.getByRole('button', { name: /chamar agora/i }))

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/appointments/appt-waiting-1/start/', {
        method: 'POST',
      })
      expect(push).toHaveBeenCalledWith('/encounters/enc-appt-waiting-1')
    })
  })
})
