import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ApprovalsPage from './page'
import { apiFetch } from '@/lib/api'

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api')
  return { ...actual, apiFetch: vi.fn() }
})

const mockedFetch = vi.mocked(apiFetch)
const approval = { id: 'a1', workflow_key: 'stock.adjustment', reference_type: 'movement', reference_id: 'M-1', title: 'Ajuste de estoque', context: {}, status: 'pending', requested_by: 'u1', created_at: '2026-07-22T12:00:00Z', steps: [{ id: 's1', sequence: 1, permission_required: 'workflow.approve', status: 'pending', decision_note: '', decided_at: null }] }

describe('ApprovalsPage', () => {
  beforeEach(() => mockedFetch.mockReset())

  it('submits an approval decision with its audit note', async () => {
    mockedFetch.mockResolvedValueOnce({ results: [approval] }).mockResolvedValueOnce({ ...approval, status: 'approved' }).mockResolvedValueOnce({ results: [] })
    render(<ApprovalsPage />)
    expect(await screen.findByText('Ajuste de estoque')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
    fireEvent.change(screen.getByLabelText('Nota da decisão'), { target: { value: 'Conferido' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledWith('/api/v1/governance/approvals/a1/approve/', expect.objectContaining({ method: 'POST', body: JSON.stringify({ note: 'Conferido' }) })))
  })
})
