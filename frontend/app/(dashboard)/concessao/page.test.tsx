import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ConcessaoPage from './page'

describe('ConcessaoPage', () => {
  it('renders the module overview with a link to each sub-area', () => {
    render(<ConcessaoPage />)

    expect(screen.getByRole('heading', { name: 'Concessão' })).toBeInTheDocument()

    expect(screen.getByRole('link', { name: /Ativos/ })).toHaveAttribute(
      'href',
      '/concessao/ativos',
    )
    expect(screen.getByRole('link', { name: /Contratos/ })).toHaveAttribute(
      'href',
      '/concessao/contratos',
    )
    expect(screen.getByRole('link', { name: /Logística/ })).toHaveAttribute(
      'href',
      '/concessao/logistica',
    )
    expect(screen.getByRole('link', { name: /P&L/ })).toHaveAttribute(
      'href',
      '/concessao/pnl',
    )
  })
})
