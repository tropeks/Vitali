import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RosterSlotGrid, { type RosterSlot } from './RosterSlotGrid'

const SLOTS: RosterSlot[] = [
  {
    id: 's1',
    roster: 'r1',
    date: '2026-08-01',
    shift: 'morning',
    start_time: '07:00:00',
    end_time: '13:00:00',
    professional: 'p1',
    employee: null,
    unit: null,
    created_at: '2026-07-01T10:00:00Z',
  },
  {
    id: 's2',
    roster: 'r1',
    date: '2026-08-01',
    shift: 'night',
    start_time: '19:00:00',
    end_time: '23:00:00',
    professional: null,
    employee: 'e1',
    unit: null,
    created_at: '2026-07-01T10:00:00Z',
  },
  {
    id: 's3',
    roster: 'r1',
    date: '2026-08-02',
    shift: 'full',
    start_time: '08:00:00',
    end_time: '18:00:00',
    professional: 'p1',
    employee: null,
    unit: null,
    created_at: '2026-07-01T10:00:00Z',
  },
]

describe('RosterSlotGrid', () => {
  it('renders an empty state when there are no slots', () => {
    render(<RosterSlotGrid slots={[]} />)
    expect(screen.getByText('Nenhum plantão nesta escala.')).toBeInTheDocument()
  })

  it('renders shift labels and time windows for each slot', () => {
    render(<RosterSlotGrid slots={SLOTS} />)

    expect(screen.getByText('Manhã')).toBeInTheDocument()
    expect(screen.getByText('Noite')).toBeInTheDocument()
    expect(screen.getByText('Integral')).toBeInTheDocument()

    // Times are rendered HH:MM (seconds stripped)
    expect(screen.getByText('07:00–13:00')).toBeInTheDocument()
    expect(screen.getByText('19:00–23:00')).toBeInTheDocument()
    expect(screen.getByText('08:00–18:00')).toBeInTheDocument()
  })

  it('groups plantões by day into one column per distinct date', () => {
    const { container } = render(<RosterSlotGrid slots={SLOTS} />)
    // Two distinct dates → two day columns
    const columns = container.querySelectorAll('[data-testid="roster-day-column"]')
    expect(columns.length).toBe(2)
  })

  it('resolves professional / employee names when maps are provided', () => {
    render(
      <RosterSlotGrid
        slots={SLOTS}
        professionalNames={{ p1: 'Dra. Ana Souza' }}
        employeeNames={{ e1: 'Bruno Lima' }}
      />
    )
    expect(screen.getAllByText('Dra. Ana Souza').length).toBeGreaterThan(0)
    expect(screen.getByText('Bruno Lima')).toBeInTheDocument()
  })
})
