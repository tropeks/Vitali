import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SettlementRow, { type Settlement } from './SettlementRow'

function row(overrides: Partial<Settlement> = {}): Settlement {
  return {
    id: 'set-1',
    professional: 'pro-1',
    professional_name: 'Dra. Ana Souza',
    competency: '2026-06',
    gross_amount: '10000.00',
    deductions: '500.00',
    net_amount: '9500.00',
    status: 'draft',
    calculated_at: null,
    paid_at: null,
    ...overrides,
  }
}

function renderRow(settlement: Settlement, handlers: Partial<{ onApprove: any; onPay: any }> = {}) {
  return render(
    <table>
      <tbody>
        <SettlementRow settlement={settlement} {...handlers} />
      </tbody>
    </table>
  )
}

describe('SettlementRow', () => {
  it('formats gross/deductions/net as BRL', () => {
    renderRow(row())
    expect(screen.getByText(/R\$\s*10\.000,00/)).toBeInTheDocument()
    expect(screen.getByText(/R\$\s*500,00/)).toBeInTheDocument()
    expect(screen.getByText(/R\$\s*9\.500,00/)).toBeInTheDocument()
  })

  it('offers only Aprovar for a draft', () => {
    const onApprove = vi.fn()
    renderRow(row({ status: 'draft' }), { onApprove, onPay: vi.fn() })
    expect(screen.getByText('Rascunho')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pagar' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aprovar' }))
    expect(onApprove).toHaveBeenCalledWith(expect.objectContaining({ id: 'set-1' }))
  })

  it('offers only Pagar for an approved settlement', () => {
    const onPay = vi.fn()
    renderRow(row({ status: 'approved' }), { onApprove: vi.fn(), onPay })
    expect(screen.getByText('Aprovado')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pagar' }))
    expect(onPay).toHaveBeenCalledWith(expect.objectContaining({ id: 'set-1' }))
  })

  it('exposes no action once paid', () => {
    renderRow(row({ status: 'paid' }), { onApprove: vi.fn(), onPay: vi.fn() })
    expect(screen.getByText('Pago')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Aprovar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pagar' })).not.toBeInTheDocument()
  })
})
