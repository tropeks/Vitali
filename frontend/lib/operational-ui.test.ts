import { describe, expect, it } from 'vitest'
import {
  buildDashboardActionQueue,
  getAppointmentStatusMeta,
  summarizePatients,
} from './operational-ui'

describe('operational-ui', () => {
  it('maps appointment status to explicit clinical metadata', () => {
    expect(getAppointmentStatusMeta('waiting')).toMatchObject({
      label: 'Aguardando',
      tone: 'attention',
    })
    expect(getAppointmentStatusMeta('no_show')).toMatchObject({
      label: 'Não compareceu',
      tone: 'critical',
    })
    expect(getAppointmentStatusMeta('unknown')).toMatchObject({
      label: 'unknown',
      tone: 'neutral',
    })
  })

  it('builds a dashboard action queue from operational risk signals', () => {
    const items = buildDashboardActionQueue({
      appointments_waiting: 3,
      appointments_confirmed: 8,
      appointments_cancelled: 1,
      appointments_no_show: 2,
      encounters_open: 4,
      encounters_signed: 10,
      wait_time_avg_min: 18.4,
    })

    expect(items).toHaveLength(3)
    expect(items[0]).toMatchObject({
      id: 'waiting-room',
      value: '3',
      detail: 'Espera média 18 min',
      tone: 'attention',
    })
    expect(items[1]).toMatchObject({
      id: 'open-encounters',
      value: '4',
      tone: 'attention',
    })
    expect(items[2]).toMatchObject({
      id: 'schedule-quality',
      value: '3',
      tone: 'critical',
    })
  })

  it('summarizes patient list risk flags without hiding inactive records', () => {
    expect(
      summarizePatients([
        { is_active: true, active_allergies_count: 2 },
        { is_active: false, active_allergies_count: 0 },
        { is_active: true, active_allergies_count: null },
      ])
    ).toEqual({
      active: 2,
      inactive: 1,
      withAllergies: 1,
    })
  })
})
