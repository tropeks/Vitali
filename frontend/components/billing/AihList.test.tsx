import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import AihList from './AihList'
import type { AihAutorizacaoLine } from './sus-types'

vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

const AIHS: AihAutorizacaoLine[] = [
  {
    id: 1,
    competencia: 7,
    numero_aih: '2026070000001',
    situacao: 'solicitada',
    procedimento_principal: 99,
    cid_principal: 'J189',
    patient: 'p1',
    data_internacao: '2026-07-01',
    data_saida: '2026-07-05',
    valor: '420.00',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AihList', () => {
  it('renders the AIH list with number, situação badge and período', () => {
    render(<AihList aihs={AIHS} canWrite onChanged={vi.fn()} />)
    expect(screen.getByText('2026070000001')).toBeInTheDocument()
    expect(screen.getByText('AIH — internação (1)')).toBeInTheDocument()
    expect(screen.getByText('Solicitada')).toBeInTheDocument()
    expect(screen.getByText(/2026-07-01/)).toBeInTheDocument()
  })

  it('opens the reconciliar modal from a solicitada AIH (sus.write)', () => {
    render(<AihList aihs={AIHS} canWrite onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reconciliar' }))
    expect(screen.getByRole('dialog', { name: 'Reconciliar AIH' })).toBeInTheDocument()
  })

  it('opens the rejeitar modal from a solicitada AIH (sus.write)', () => {
    render(<AihList aihs={AIHS} canWrite onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Rejeitar' }))
    expect(screen.getByRole('dialog', { name: 'Rejeitar AIH' })).toBeInTheDocument()
  })

  it('hides reconciliar/rejeitar actions without sus.write', () => {
    render(<AihList aihs={AIHS} canWrite={false} onChanged={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Reconciliar' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rejeitar' })).not.toBeInTheDocument()
  })

  it('hides reconciliar on an already autorizada AIH', () => {
    render(
      <AihList aihs={[{ ...AIHS[0], situacao: 'autorizada' }]} canWrite onChanged={vi.fn()} />
    )
    expect(screen.queryByRole('button', { name: 'Reconciliar' })).not.toBeInTheDocument()
    expect(screen.getByText('Autorizada')).toBeInTheDocument()
  })

  it('shows an empty state when there are no AIHs', () => {
    render(<AihList aihs={[]} canWrite onChanged={vi.fn()} />)
    expect(screen.getByText('Nenhuma AIH')).toBeInTheDocument()
  })
})
