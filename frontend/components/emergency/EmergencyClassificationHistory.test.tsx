import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import EmergencyClassificationHistory from './EmergencyClassificationHistory'

const HISTORY = [
  {
    id: 'rc-1',
    boletim: 'bol-1',
    flowchart: 'fc-1',
    flowchart_code: 'DOR-TORAX',
    discriminator: 'disc-1',
    discriminator_code: 'DOR-PRECORDIAL',
    acuity_level: 'laranja',
    target_minutes: 10,
    classified_at: '2026-07-25T13:00:00Z',
    notes: 're-triagem',
  },
  {
    id: 'rc-0',
    boletim: 'bol-1',
    flowchart: 'fc-1',
    flowchart_code: 'DOR-TORAX',
    discriminator: 'disc-0',
    discriminator_code: 'DESCONFORTO',
    acuity_level: 'amarelo',
    target_minutes: 60,
    classified_at: '2026-07-25T12:40:00Z',
    notes: '',
  },
]

describe('EmergencyClassificationHistory', () => {
  it('renders an empty state with no classifications', () => {
    render(<EmergencyClassificationHistory classifications={[]} />)
    expect(screen.getByText('Sem classificação de risco')).toBeInTheDocument()
  })

  it('renders every append-only entry, flagging the newest as Atual', () => {
    render(<EmergencyClassificationHistory classifications={HISTORY} />)
    // Both acuity levels rendered (append-only trail preserved).
    expect(screen.getByText('Laranja (muito urgente)')).toBeInTheDocument()
    expect(screen.getByText('Amarelo (urgente)')).toBeInTheDocument()
    expect(screen.getByText(/DOR-PRECORDIAL/)).toBeInTheDocument()
    expect(screen.getByText(/DESCONFORTO/)).toBeInTheDocument()
    // Only the first (newest) is flagged current.
    expect(screen.getAllByText('Atual')).toHaveLength(1)
  })
})
