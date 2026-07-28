import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ReceivableTable from './ReceivableTable'
import type { Receivable } from './financeFormat'

const base: Receivable = {
  id: 'r1',
  guide_number: 'G-1',
  patient_name: 'Maria Oliveira',
  provider_name: 'Unimed',
  amount: '900.00',
  due_date: '2026-08-05',
  received_at: null,
  status: 'billed',
  notes: '',
  created_at: '',
  updated_at: '',
}

describe('ReceivableTable', () => {
  it('shows Dar baixa for an open receivable and calls onMarkReceived', () => {
    const onMarkReceived = vi.fn()
    render(<ReceivableTable receivables={[base]} onMarkReceived={onMarkReceived} />)
    expect(screen.getByText('Maria Oliveira')).toBeInTheDocument()
    expect(screen.getByText('R$ 900,00')).toBeInTheDocument()
    expect(screen.getByText('Faturado')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Dar baixa' }))
    expect(onMarkReceived).toHaveBeenCalledWith(base)
  })

  it('renders no baixa button once received', () => {
    render(<ReceivableTable receivables={[{ ...base, status: 'received' }]} onMarkReceived={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Dar baixa' })).toBeNull()
    expect(screen.getByText('Recebido')).toBeInTheDocument()
  })
})
