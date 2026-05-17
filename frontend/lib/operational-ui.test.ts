import { describe, expect, it } from 'vitest'
import {
  buildDashboardActionQueue,
  getAppointmentStatusMeta,
  getStockStatusMeta,
  GUIDE_STATUS_META,
  PRESCRIPTION_STATUS_META,
  resolveBadgeMeta,
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

  it('resolves badge meta against a map and echoes unknown values', () => {
    expect(resolveBadgeMeta(GUIDE_STATUS_META, 'paid')).toMatchObject({
      label: 'Paga',
      tone: 'success',
    })
    // canonical label wins for a known status, even if the server sent a
    // different status_display — the map is the single source of truth
    expect(resolveBadgeMeta(GUIDE_STATUS_META, 'denied', 'Glosada parcial')).toMatchObject({
      label: 'Glosada',
      tone: 'critical',
    })
    // unknown status falls back to the server display string, then raw value
    expect(resolveBadgeMeta(GUIDE_STATUS_META, 'mystery', 'Status do servidor')).toMatchObject({
      label: 'Status do servidor',
      tone: 'neutral',
    })
    expect(resolveBadgeMeta(GUIDE_STATUS_META, 'mystery')).toMatchObject({
      label: 'mystery',
      tone: 'neutral',
    })
    expect(resolveBadgeMeta(GUIDE_STATUS_META, null)).toMatchObject({
      label: 'Indefinido',
    })
  })

  it('keeps a signed prescription blue (actionable), not green (completed)', () => {
    expect(PRESCRIPTION_STATUS_META.signed.tone).toBe('info')
    expect(PRESCRIPTION_STATUS_META.signed.badgeClass).toContain('blue')
    expect(PRESCRIPTION_STATUS_META.dispensed.badgeClass).toContain('green')
  })

  it('derives stock alert badges from expiry and low-stock signals', () => {
    expect(getStockStatusMeta({ is_expired: true })).toMatchObject({
      label: 'Vencido',
      tone: 'critical',
    })
    const soon = new Date()
    soon.setDate(soon.getDate() + 10)
    expect(
      getStockStatusMeta({ expiry_date: soon.toISOString().slice(0, 10) })
    ).toMatchObject({ tone: 'attention' })
    expect(getStockStatusMeta({ is_low_stock: true })).toMatchObject({
      label: 'Estoque baixo',
    })
    expect(getStockStatusMeta({ is_expired: false, is_low_stock: false })).toBeNull()
  })
})
