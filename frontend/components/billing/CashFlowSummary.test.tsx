import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CashFlowSummary from './CashFlowSummary'

describe('CashFlowSummary', () => {
  it('renders BRL totals and the derived balance', () => {
    render(<CashFlowSummary inflow={1000} outflow={400} forecastCount={2} />)
    expect(screen.getByText('R$ 1.000,00')).toBeInTheDocument()
    expect(screen.getByText('R$ 400,00')).toBeInTheDocument()
    expect(screen.getByText('R$ 600,00')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('shows a negative balance when outflow exceeds inflow', () => {
    render(<CashFlowSummary inflow={100} outflow={250} forecastCount={0} />)
    // toLocaleString pt-BR renders negative currency as -R$ 150,00
    expect(screen.getByText('-R$ 150,00')).toBeInTheDocument()
  })
})
