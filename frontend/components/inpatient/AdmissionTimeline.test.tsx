import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import AdmissionTimeline from './AdmissionTimeline'
import type { AdmissionEvent } from './admission-types'

const ADMIT: AdmissionEvent = {
  id: 'ev-1',
  admission: 'adm-1',
  event_type: 'admit',
  from_bed: null,
  to_bed: 'bed-1',
  reason: '',
  created_at: '2026-07-20T10:00:00Z',
}

const TRANSFER: AdmissionEvent = {
  id: 'ev-2',
  admission: 'adm-1',
  event_type: 'transfer',
  from_bed: 'bed-1',
  to_bed: 'bed-2',
  reason: 'Vaga em UTI',
  created_at: '2026-07-21T08:00:00Z',
}

describe('AdmissionTimeline', () => {
  it('shows an empty state when there are no events', () => {
    render(<AdmissionTimeline events={[]} />)
    expect(screen.getByText('Sem eventos ADT')).toBeInTheDocument()
  })

  it('renders each ADT event with its type label', () => {
    render(<AdmissionTimeline events={[ADMIT, TRANSFER]} />)
    expect(screen.getByText('Admissão')).toBeInTheDocument()
    expect(screen.getByText('Transferência')).toBeInTheDocument()
    expect(screen.getByText('Vaga em UTI')).toBeInTheDocument()
  })

  it('resolves bed ids to identifiers from the bedLabels map', () => {
    render(
      <AdmissionTimeline
        events={[TRANSFER]}
        bedLabels={{ 'bed-1': 'L-01', 'bed-2': 'L-02' }}
      />,
    )
    expect(screen.getByText('L-01 → L-02')).toBeInTheDocument()
  })
})
