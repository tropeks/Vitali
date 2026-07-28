import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import BcmaFiveRights from './BcmaFiveRights'
import type { FiveRights } from './mar-types'

const ALL_OK: FiveRights = {
  patient: true,
  medication: true,
  dose: true,
  route: true,
  time: true,
  ok: true,
  mismatches: [],
}

const MED_FAILED: FiveRights = {
  patient: true,
  medication: false,
  dose: true,
  route: false,
  time: true,
  ok: false,
  mismatches: ['medication', 'route'],
}

describe('BcmaFiveRights', () => {
  it('renders all five rights in pt-BR', () => {
    render(<BcmaFiveRights result={ALL_OK} />)
    expect(screen.getByText('Paciente')).toBeInTheDocument()
    expect(screen.getByText('Medicamento')).toBeInTheDocument()
    expect(screen.getByText('Dose')).toBeInTheDocument()
    expect(screen.getByText('Via')).toBeInTheDocument()
    expect(screen.getByText('Hora')).toBeInTheDocument()
  })

  it('marks the failed rights as "Falhou" and the passing ones as "Certo"', () => {
    render(<BcmaFiveRights result={MED_FAILED} />)
    // medication + route failed → two "Falhou"; patient/dose/time passed → three "Certo"
    expect(screen.getAllByText('Falhou')).toHaveLength(2)
    expect(screen.getAllByText('Certo')).toHaveLength(3)
  })

  it('highlights the failed right rows (destaque via row test id)', () => {
    render(<BcmaFiveRights result={MED_FAILED} />)
    const medRow = screen.getByTestId('bcma-right-medication')
    expect(medRow.className).toContain('border-red')
    const patientRow = screen.getByTestId('bcma-right-patient')
    expect(patientRow.className).not.toContain('border-red')
  })
})
