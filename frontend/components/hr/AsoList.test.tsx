import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AsoList from './AsoList'

const EMPLOYEES = [
  { id: 'emp-1', full_name: 'Ana Souza' },
  { id: 'emp-2', full_name: 'Bruno Lima' },
]

const FIT_EXAM = {
  id: 'aso-1',
  employee: 'emp-1',
  exam_type: 'periodic' as const,
  performed_on: '2026-01-10',
  expires_on: '2027-01-10',
  result: 'fit' as const,
  provider_name: 'Dr. Carlos Nunes',
  recorded_by: 'user-1',
  created_at: '2026-01-10T10:00:00Z',
  updated_at: '2026-01-10T10:00:00Z',
}

const EXPIRED_EXAM = {
  id: 'aso-2',
  employee: 'emp-2',
  exam_type: 'admission' as const,
  performed_on: '2025-01-01',
  expires_on: '2026-01-01',
  result: 'unfit' as const,
  provider_name: 'Dra. Marta Reis',
  recorded_by: 'user-2',
  created_at: '2025-01-01T10:00:00Z',
  updated_at: '2025-01-01T10:00:00Z',
}

describe('AsoList', () => {
  it('renders an empty state when there are no exams', () => {
    render(<AsoList exams={[]} employees={EMPLOYEES} />)
    expect(screen.getByText(/Nenhum ASO registrado/i)).toBeInTheDocument()
  })

  it('resolves employee names and shows the aptitude badge', () => {
    render(<AsoList exams={[FIT_EXAM, EXPIRED_EXAM]} employees={EMPLOYEES} />)

    expect(screen.getByText('Ana Souza')).toBeInTheDocument()
    expect(screen.getByText('Bruno Lima')).toBeInTheDocument()
    expect(screen.getByText('Apto')).toBeInTheDocument()
    expect(screen.getByText('Inapto')).toBeInTheDocument()
  })

  it('highlights an expired exam expiry date', () => {
    render(<AsoList exams={[EXPIRED_EXAM]} employees={EMPLOYEES} referenceDate="2026-07-24" />)

    const expiry = screen.getByText('01/01/2026')
    expect(expiry.className).toContain('text-neu-danger')
    expect(screen.getByText(/vencido/i)).toBeInTheDocument()
  })

  it('does not highlight a far-future expiry date', () => {
    render(<AsoList exams={[FIT_EXAM]} employees={EMPLOYEES} referenceDate="2026-07-24" />)

    const expiry = screen.getByText('10/01/2027')
    expect(expiry.className).not.toContain('text-neu-danger')
  })
})
