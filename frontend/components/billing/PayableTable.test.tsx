import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PayableTable from './PayableTable'
import type { Payable } from './financeFormat'

const base: Payable = {
  id: 'p1',
  external_id: 'nf-1',
  description: 'Aluguel',
  category: 'Ocupação',
  amount: '2500.00',
  due_date: '2026-08-10',
  paid_at: null,
  status: 'planned',
  notes: '',
  created_at: '',
  updated_at: '',
}

describe('PayableTable', () => {
  it('shows Aprovar for planned and calls onApprove', () => {
    const onApprove = vi.fn()
    render(<PayableTable payables={[base]} onApprove={onApprove} onPay={vi.fn()} />)
    expect(screen.getByText('R$ 2.500,00')).toBeInTheDocument()
    expect(screen.getByText('Prevista')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
    expect(onApprove).toHaveBeenCalledWith(base)
  })

  it('shows Pagar for approved and calls onPay', () => {
    const onPay = vi.fn()
    const approved = { ...base, id: 'p2', status: 'approved' }
    render(<PayableTable payables={[approved]} onApprove={vi.fn()} onPay={onPay} />)
    fireEvent.click(screen.getByRole('button', { name: 'Pagar' }))
    expect(onPay).toHaveBeenCalledWith(approved)
  })

  it('renders no action button for a paid payable', () => {
    render(<PayableTable payables={[{ ...base, status: 'paid' }]} onApprove={vi.fn()} onPay={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Aprovar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Pagar' })).toBeNull()
    expect(screen.getByText('Paga')).toBeInTheDocument()
  })
})
