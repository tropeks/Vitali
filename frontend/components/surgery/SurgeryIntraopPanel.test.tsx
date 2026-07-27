import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiError } from '@/lib/api'
import SurgeryIntraopPanel from './SurgeryIntraopPanel'

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

const onBack = vi.fn()

const FULL_TIMELINE = {
  case: 'case-1',
  status: 'em_andamento',
  times: [
    { id: 't1', case: 'case-1', event: 'sala_entrada', recorded_at: '2026-07-25T13:00:00Z' },
  ],
  checklists: [
    {
      id: 'c1',
      case: 'case-1',
      phase: 'sign_in',
      items: { identidade_confirmada: true },
      confirmed_at: '2026-07-25T13:05:00Z',
    },
  ],
  team: [
    { id: 'm1', case: 'case-1', professional: 'prof-1', professional_name: 'Dr. House', role: 'cirurgiao' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SurgeryIntraopPanel', () => {
  it('renders the case status prominently plus times, checklist and team (read)', async () => {
    mockApiFetch.mockResolvedValue(FULL_TIMELINE)
    render(<SurgeryIntraopPanel caseId="case-1" canManage={false} onBack={onBack} />)

    await waitFor(() => {
      expect(screen.getByText('Tempos cirúrgicos')).toBeInTheDocument()
    })
    // Current status prominent (heading + badge).
    expect(screen.getAllByText('Em andamento').length).toBeGreaterThan(0)
    // Ordered timeline: a recorded event and a pending one.
    expect(screen.getByText('Entrada na sala')).toBeInTheDocument()
    expect(screen.getAllByText('Pendente').length).toBeGreaterThan(0)
    // Confirmed checklist phase.
    expect(screen.getByText('Sign in (antes da anestesia)')).toBeInTheDocument()
    expect(screen.getByText('Fase confirmada')).toBeInTheDocument()
    // Team member + role.
    expect(screen.getByText('Dr. House')).toBeInTheDocument()
    expect(screen.getByText('Cirurgião')).toBeInTheDocument()
  })

  it('hides every write control without surgery.manage', async () => {
    mockApiFetch.mockResolvedValue(FULL_TIMELINE)
    render(<SurgeryIntraopPanel caseId="case-1" canManage={false} onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getByText('Tempos cirúrgicos')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /Registrar tempo/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirmar fase/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Adicionar à equipe/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remover/ })).not.toBeInTheDocument()
  })

  it('records the next time and reflects the advanced case status', async () => {
    let timeline: any = {
      case: 'case-1',
      status: 'em_sala',
      times: [
        { id: 't1', case: 'case-1', event: 'sala_entrada', recorded_at: '2026-07-25T13:00:00Z' },
        { id: 't2', case: 'case-1', event: 'anestesia_inicio', recorded_at: '2026-07-25T13:05:00Z' },
        { id: 't3', case: 'case-1', event: 'anestesia_fim', recorded_at: '2026-07-25T13:20:00Z' },
      ],
      checklists: [],
      team: [],
    }
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/record-time/') && opts?.method === 'POST') {
        // incisao advances the case: em_sala → em_andamento.
        timeline = {
          ...timeline,
          status: 'em_andamento',
          times: [
            ...timeline.times,
            { id: 't4', case: 'case-1', event: 'incisao', recorded_at: '2026-07-25T13:30:00Z' },
          ],
        }
        return Promise.resolve({})
      }
      if (url.includes('/timeline/')) return Promise.resolve(timeline)
      return Promise.resolve([])
    })

    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getAllByText('Em sala').length).toBeGreaterThan(0)
    })

    // Next un-recorded event is "incisao" (default selection).
    fireEvent.click(screen.getByRole('button', { name: /Registrar tempo/ }))

    await waitFor(() => {
      const post = mockApiFetch.mock.calls.find(
        ([url, o]) => url === '/api/v1/surgical-cases/case-1/record-time/' && o?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(JSON.parse(post![1].body).event).toBe('incisao')
    })
    // Status advanced after the reload.
    await waitFor(() => {
      expect(screen.getAllByText('Em andamento').length).toBeGreaterThan(0)
    })
  })

  it('surfaces an out-of-order record-time 409 as "fora de ordem"', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/record-time/') && opts?.method === 'POST') {
        return Promise.reject(new ApiError(409, { detail: 'fora de ordem' }))
      }
      if (url.includes('/timeline/')) {
        return Promise.resolve({ case: 'case-1', status: 'confirmada', times: [], checklists: [], team: [] })
      }
      return Promise.resolve([])
    })

    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Registrar tempo/ })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /Registrar tempo/ }))

    await waitFor(() => {
      expect(screen.getByText(/fora de ordem/i)).toBeInTheDocument()
    })
  })

  it('confirms a checklist phase and shows it done after reload', async () => {
    let timeline: any = {
      case: 'case-1',
      status: 'confirmada',
      times: [],
      checklists: [],
      team: [],
    }
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/checklist/') && opts?.method === 'POST') {
        timeline = {
          ...timeline,
          checklists: [
            { id: 'c1', case: 'case-1', phase: 'sign_in', items: {}, confirmed_at: '2026-07-25T13:00:00Z' },
          ],
        }
        return Promise.resolve({ id: 'c1' })
      }
      if (url.includes('/timeline/')) return Promise.resolve(timeline)
      return Promise.resolve([])
    })

    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Confirmar fase' }).length).toBe(3)
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Confirmar fase' })[0])

    await waitFor(() => {
      const post = mockApiFetch.mock.calls.find(
        ([url, o]) => url === '/api/v1/surgical-cases/case-1/checklist/' && o?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(JSON.parse(post![1].body).phase).toBe('sign_in')
    })
    await waitFor(() => {
      expect(screen.getByText('Fase confirmada')).toBeInTheDocument()
    })
  })

  it('treats an already-confirmed phase (409) as done', async () => {
    let timeline: any = {
      case: 'case-1',
      status: 'confirmada',
      times: [],
      checklists: [],
      team: [],
    }
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/checklist/') && opts?.method === 'POST') {
        // Confirmed concurrently elsewhere; the reload will show it done.
        timeline = {
          ...timeline,
          checklists: [
            { id: 'c1', case: 'case-1', phase: 'sign_in', items: {}, confirmed_at: '2026-07-25T13:00:00Z' },
          ],
        }
        return Promise.reject(new ApiError(409, { detail: 'já confirmada' }))
      }
      if (url.includes('/timeline/')) return Promise.resolve(timeline)
      return Promise.resolve([])
    })

    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Confirmar fase' }).length).toBe(3)
    })

    fireEvent.click(screen.getAllByRole('button', { name: 'Confirmar fase' })[0])

    await waitFor(() => {
      expect(screen.getByText('Fase confirmada')).toBeInTheDocument()
    })
  })

  it('adds a team member (POST surgical-team with case/professional/role)', async () => {
    let timeline: any = { case: 'case-1', status: 'confirmada', times: [], checklists: [], team: [] }
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url === '/api/v1/surgical-team/' && opts?.method === 'POST') {
        timeline = {
          ...timeline,
          team: [
            { id: 'm1', case: 'case-1', professional: 'prof-9', professional_name: 'Dra. Ana', role: 'anestesista' },
          ],
        }
        return Promise.resolve({ id: 'm1' })
      }
      if (url.startsWith('/api/v1/professionals/')) {
        return Promise.resolve([{ id: 'prof-9', user_name: 'Dra. Ana' }])
      }
      if (url.includes('/timeline/')) return Promise.resolve(timeline)
      return Promise.resolve([])
    })

    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Adicionar à equipe/ })).toBeInTheDocument()
    })

    // Drive the RemoteCombobox: focus fetches professionals, then pick one.
    fireEvent.focus(screen.getByRole('combobox', { name: 'Profissional' }))
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Dra. Ana' })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('option', { name: 'Dra. Ana' }))

    fireEvent.click(screen.getByRole('button', { name: /Adicionar à equipe/ }))

    await waitFor(() => {
      const post = mockApiFetch.mock.calls.find(
        ([url, o]) => url === '/api/v1/surgical-team/' && o?.method === 'POST',
      )
      expect(post).toBeTruthy()
      const body = JSON.parse(post![1].body)
      expect(body.case).toBe('case-1')
      expect(body.professional).toBe('prof-9')
      expect(body.role).toBe('cirurgiao')
    })
    await waitFor(() => {
      expect(screen.getByText('Dra. Ana')).toBeInTheDocument()
    })
  })

  it('surfaces a duplicate team member (400) as a friendly message', async () => {
    mockApiFetch.mockImplementation((url: string, opts?: any) => {
      if (url === '/api/v1/surgical-team/' && opts?.method === 'POST') {
        return Promise.reject(new ApiError(400, { detail: 'dup' }))
      }
      if (url.startsWith('/api/v1/professionals/')) {
        return Promise.resolve([{ id: 'prof-9', user_name: 'Dra. Ana' }])
      }
      if (url.includes('/timeline/')) {
        return Promise.resolve({ case: 'case-1', status: 'confirmada', times: [], checklists: [], team: [] })
      }
      return Promise.resolve([])
    })

    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Adicionar à equipe/ })).toBeInTheDocument()
    })

    fireEvent.focus(screen.getByRole('combobox', { name: 'Profissional' }))
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Dra. Ana' })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('option', { name: 'Dra. Ana' }))
    fireEvent.click(screen.getByRole('button', { name: /Adicionar à equipe/ }))

    await waitFor(() => {
      expect(
        screen.getByText('Este profissional já ocupa essa função no caso.'),
      ).toBeInTheDocument()
    })
  })

  it('shows an error state when the timeline fetch fails', async () => {
    mockApiFetch.mockRejectedValueOnce(new Error('boom'))
    render(<SurgeryIntraopPanel caseId="case-1" canManage onBack={onBack} />)
    await waitFor(() => {
      expect(screen.getByText('Erro ao carregar prontuário cirúrgico')).toBeInTheDocument()
    })
  })
})
