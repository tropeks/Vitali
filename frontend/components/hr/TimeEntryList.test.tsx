import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import TimeEntryList from './TimeEntryList'

const EMPLOYEES = [
  { id: 'emp-1', full_name: 'Ana Souza' },
  { id: 'emp-2', full_name: 'Bruno Lima' },
]

const ENTRY_1 = {
  id: 'te-1',
  employee: 'emp-1',
  event_type: 'in' as const,
  occurred_at: '2026-07-24T08:00:00Z',
  source: 'web' as const,
  recorded_by: 'user-1',
  created_at: '2026-07-24T08:00:00Z',
}

const ENTRY_2 = {
  id: 'te-2',
  employee: 'emp-2',
  event_type: 'out' as const,
  occurred_at: '2026-07-24T17:00:00Z',
  source: 'mobile' as const,
  recorded_by: 'user-2',
  created_at: '2026-07-24T17:00:00Z',
}

describe('TimeEntryList', () => {
  it('renders an empty state when there are no entries', () => {
    render(<TimeEntryList entries={[]} employees={EMPLOYEES} />)
    expect(screen.getByText(/Nenhuma marcação de ponto/i)).toBeInTheDocument()
  })

  it('resolves employee names via the employees list and shows type/source labels', () => {
    render(<TimeEntryList entries={[ENTRY_1, ENTRY_2]} employees={EMPLOYEES} />)

    expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    expect(screen.getByText('Bruno Lima')).toBeInTheDocument()
    expect(screen.getByText('Entrada')).toBeInTheDocument()
    expect(screen.getByText('Saída')).toBeInTheDocument()
    expect(screen.getByText('Mobile')).toBeInTheDocument()
  })

  it('falls back to the raw employee id when not found in the employees list', () => {
    render(<TimeEntryList entries={[ENTRY_1]} employees={[]} />)
    expect(screen.getByText('emp-1')).toBeInTheDocument()
  })
})
