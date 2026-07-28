import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProfessionalRow, { type Professional } from './ProfessionalRow'

const BASE: Professional = {
  id: 'pro-1',
  user: 'user-1',
  user_name: 'Dra. Ana Souza',
  user_email: 'ana@clinica.com',
  council_type: 'CRM',
  council_type_display: 'CRM',
  council_number: '12345',
  council_state: 'SP',
  specialty: 'Clínica Médica',
  cbo_code: null,
  cnes_code: null,
  cbo_unmatched: false,
  cnes_unmatched: false,
  is_active: true,
  created_at: '2024-01-15T10:00:00Z',
}

function renderRow(professional: Professional, onEdit = vi.fn()) {
  return render(
    <table>
      <tbody>
        <ProfessionalRow professional={professional} onEdit={onEdit} />
      </tbody>
    </table>
  )
}

describe('ProfessionalRow', () => {
  it('shows the governed code with no badge when reconciled', () => {
    renderRow({ ...BASE, cbo_code: '2231-05', cbo_unmatched: false })

    expect(screen.getByText('2231-05')).toBeInTheDocument()
    expect(screen.queryByText('não reconciliado')).not.toBeInTheDocument()
  })

  it('shows a "não reconciliado" badge when cbo_unmatched is true', () => {
    renderRow({ ...BASE, cbo_code: '9999-99', cbo_unmatched: true })

    expect(screen.getByText('9999-99')).toBeInTheDocument()
    expect(screen.getAllByText('não reconciliado').length).toBeGreaterThan(0)
  })

  it('shows a "não reconciliado" badge when cnes_unmatched is true', () => {
    renderRow({ ...BASE, cnes_code: '0000000', cnes_unmatched: true })

    expect(screen.getByText('0000000')).toBeInTheDocument()
    expect(screen.getAllByText('não reconciliado').length).toBeGreaterThan(0)
  })

  it('calls onEdit with the professional when Editar is clicked', () => {
    const onEdit = vi.fn()
    renderRow(BASE, onEdit)

    screen.getByRole('button', { name: 'Editar' }).click()

    expect(onEdit).toHaveBeenCalledWith(BASE)
  })
})
