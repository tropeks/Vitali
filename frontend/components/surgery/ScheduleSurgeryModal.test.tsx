import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { apiFetch, ApiError } from '@/lib/api'
import ScheduleSurgeryModal from './ScheduleSurgeryModal'

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

const ROOMS = [
  { id: 'or1', code: 'SO-01', name: 'Sala 1' },
  { id: 'or2', code: 'SO-02', name: 'Sala 2' },
]

const UNSCHEDULED = [
  {
    id: 'case-abc12345',
    patient: 'p1',
    surgeon: 's1',
    operating_room: null,
    scheduled_start: null,
    scheduled_end: null,
    priority: 'eletiva',
    status: 'agendada',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ScheduleSurgeryModal — schedule mode', () => {
  it('schedules an existing unscheduled case (POST schedule)', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/surgical-cases/?status=agendada')) return Promise.resolve(UNSCHEDULED)
      if (url.includes('/schedule/') && opts?.method === 'POST') return Promise.resolve({})
      return Promise.resolve({})
    })
    const onDone = vi.fn()
    render(
      <ScheduleSurgeryModal
        mode="schedule"
        rooms={ROOMS}
        defaultDate="2026-07-24"
        canManage={false}
        onClose={vi.fn()}
        onDone={onDone}
      />
    )

    // Existing-case select is populated from the unscheduled fetch.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Caso #case-abc/ })).toBeInTheDocument()
    )
    fireEvent.change(screen.getByLabelText('Caso a agendar'), {
      target: { value: 'case-abc12345' },
    })
    fireEvent.change(screen.getByLabelText('Sala cirúrgica'), { target: { value: 'or1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Agendar' }))

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const scheduleCall = mockApiFetch.mock.calls.find(([url, opts]) =>
      String(url).includes('/surgical-cases/case-abc12345/schedule/') &&
      (opts as any)?.method === 'POST'
    )
    expect(scheduleCall).toBeTruthy()
    const body = JSON.parse((scheduleCall![1] as any).body)
    expect(body.operating_room).toBe('or1')
    expect(body.scheduled_start).toBeTruthy()
    expect(body.scheduled_end).toBeTruthy()
  })

  it('surfaces an overlap 409 as "conflito de horário na sala"', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/surgical-cases/?status=agendada')) return Promise.resolve(UNSCHEDULED)
      if (url.includes('/schedule/') && opts?.method === 'POST') {
        return Promise.reject(new ApiError(409, { detail: 'conflito' }))
      }
      return Promise.resolve({})
    })
    const onDone = vi.fn()
    render(
      <ScheduleSurgeryModal
        mode="schedule"
        rooms={ROOMS}
        defaultDate="2026-07-24"
        canManage={false}
        onClose={vi.fn()}
        onDone={onDone}
      />
    )
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Caso #case-abc/ })).toBeInTheDocument()
    )
    fireEvent.change(screen.getByLabelText('Caso a agendar'), {
      target: { value: 'case-abc12345' },
    })
    fireEvent.change(screen.getByLabelText('Sala cirúrgica'), { target: { value: 'or1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Agendar' }))

    await waitFor(() =>
      expect(screen.getByText(/Conflito de horário na sala/)).toBeInTheDocument()
    )
    expect(onDone).not.toHaveBeenCalled()
  })

  it('offers the "novo caso" create sub-form when canManage', async () => {
    mockApiFetch.mockResolvedValue([])
    render(
      <ScheduleSurgeryModal
        mode="schedule"
        rooms={ROOMS}
        defaultDate="2026-07-24"
        canManage
        onClose={vi.fn()}
        onDone={vi.fn()}
      />
    )
    // Default source is "novo caso" → patient + surgeon comboboxes present.
    expect(screen.getByRole('radio', { name: 'Novo caso' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    // Patient + surgeon pickers (RemoteCombobox) are shown.
    expect(screen.getAllByRole('combobox').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByPlaceholderText('Buscar paciente...')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Buscar cirurgião...')).toBeInTheDocument()
  })
})

describe('ScheduleSurgeryModal — reschedule mode', () => {
  it('reschedules a case (POST reschedule) without loading unscheduled cases', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/reschedule/') && opts?.method === 'POST') return Promise.resolve({})
      return Promise.resolve({})
    })
    const onDone = vi.fn()
    render(
      <ScheduleSurgeryModal
        mode="reschedule"
        rooms={ROOMS}
        defaultDate="2026-07-24"
        canManage={false}
        caseId="c9"
        currentRoomId="or1"
        currentStart="2026-07-24T11:00:00Z"
        currentEnd="2026-07-24T12:00:00Z"
        onClose={vi.fn()}
        onDone={onDone}
      />
    )
    expect(screen.getByRole('dialog', { name: 'Reagendar cirurgia' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Sala cirúrgica'), { target: { value: 'or2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reagendar' }))

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const call = mockApiFetch.mock.calls.find(([url]) =>
      String(url).includes('/surgical-cases/c9/reschedule/')
    )
    expect(call).toBeTruthy()
    expect(JSON.parse((call![1] as any).body).operating_room).toBe('or2')
    // No unscheduled fetch in reschedule mode.
    expect(
      mockApiFetch.mock.calls.some(([url]) =>
        String(url).includes('?status=agendada')
      )
    ).toBe(false)
  })
})
