import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import LeaveRequestList from './LeaveRequestList'

const base = {
  employee: 'e',
  leave_type: 'ferias',
  leave_type_display: 'Férias',
  start_date: '2026-08-01',
  end_date: '2026-08-10',
  reason: 'x',
  approval: null,
  created_at: '2026-07-20T10:00:00Z',
  updated_at: '2026-07-20T10:00:00Z',
}

const own = { ...base, id: 'lr-1', employee_name: 'Ana', status: 'pending', requested_by: 'user-1' }
const other = { ...base, id: 'lr-2', employee_name: 'Bruno', status: 'pending', requested_by: 'user-2' }
const decided = { ...base, id: 'lr-3', employee_name: 'Carla', status: 'approved', requested_by: 'user-2' }

describe('LeaveRequestList', () => {
  it('renders an empty state when there are no requests', () => {
    render(<LeaveRequestList requests={[]} currentUserId="user-1" onDecide={() => {}} />)
    expect(screen.getByText('Nenhuma solicitação de afastamento ainda.')).toBeInTheDocument()
  })

  it('shows a Decidir action only for other people pending requests', () => {
    const onDecide = vi.fn()
    render(
      <LeaveRequestList
        requests={[own as any, other as any, decided as any]}
        currentUserId="user-1"
        onDecide={onDecide}
      />
    )

    // own pending (user-1) → no decide button; other pending (user-2) → one button;
    // decided (approved) → no button.
    const buttons = screen.getAllByRole('button', { name: /Decidir/ })
    expect(buttons).toHaveLength(1)

    // The maker-checker rule is surfaced on the own request.
    expect(screen.getByText(/própria solicitação/i)).toBeInTheDocument()

    fireEvent.click(buttons[0])
    expect(onDecide).toHaveBeenCalledWith(other)
  })
})
