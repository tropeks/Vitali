import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import SurgicalCaseBlock from './SurgicalCaseBlock'
import type { BoardCase } from './surgery-board-types'

function makeCase(overrides: Partial<BoardCase> = {}): BoardCase {
  return {
    id: 'c1',
    patient: { id: 'p1', name: 'Maria Silva' },
    surgeon: { id: 's1', name: 'Dr. Ana Souza' },
    scheduled_start: '2026-07-24T11:00:00Z',
    scheduled_end: '2026-07-24T12:30:00Z',
    status: 'agendada',
    priority: 'eletiva',
    procedures: [{ tuss_code: '30731100', description: 'Apendicectomia', quantity: 1 }],
    ...overrides,
  }
}

describe('SurgicalCaseBlock', () => {
  it('renders patient, surgeon, status label and procedures count', () => {
    render(
      <SurgicalCaseBlock
        surgicalCase={makeCase()}
        canSchedule={false}
        onConfirm={vi.fn()}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
      />
    )
    expect(screen.getByText('Maria Silva')).toBeInTheDocument()
    expect(screen.getByText('Dr. Ana Souza')).toBeInTheDocument()
    expect(screen.getByText('Agendada')).toBeInTheDocument()
    expect(screen.getByText('1 procedimento')).toBeInTheDocument()
  })

  it('applies a priority accent + badge for urgência/emergência', () => {
    render(
      <SurgicalCaseBlock
        surgicalCase={makeCase({ priority: 'emergencia' })}
        canSchedule={false}
        onConfirm={vi.fn()}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
      />
    )
    expect(screen.getByText('Emergência')).toBeInTheDocument()
    const block = screen.getByRole('article', { name: /Cirurgia de Maria Silva/ })
    expect(block.className).toContain('border-l-4')
  })

  it('hides the lifecycle actions without surgery.schedule', () => {
    render(
      <SurgicalCaseBlock
        surgicalCase={makeCase()}
        canSchedule={false}
        onConfirm={vi.fn()}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reagendar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancelar' })).not.toBeInTheDocument()
  })

  it('shows Confirmar only for agendada and fires the callbacks', () => {
    const onConfirm = vi.fn()
    const onReschedule = vi.fn()
    const onCancel = vi.fn()
    render(
      <SurgicalCaseBlock
        surgicalCase={makeCase()}
        canSchedule
        onConfirm={onConfirm}
        onReschedule={onReschedule}
        onCancel={onCancel}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reagendar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }))
    expect(onReschedule).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }))
    expect(onCancel).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }))
  })

  it('drops Confirmar once the case is confirmada (only reagendar/cancelar remain)', () => {
    render(
      <SurgicalCaseBlock
        surgicalCase={makeCase({ status: 'confirmada' })}
        canSchedule
        onConfirm={vi.fn()}
        onReschedule={vi.fn()}
        onCancel={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reagendar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument()
  })
})
