import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ApiError } from './api'
import {
  isDoseSafetyBlock,
  isWeightGate,
  acknowledgeDoseAlert,
  type DoseAlert,
} from './dose-safety'

vi.mock('./auth', () => ({
  getAccessToken: vi.fn(() => 'test-token'),
}))

function makeAlert(overrides: Partial<DoseAlert> = {}): DoseAlert {
  return {
    id: 'alert-1',
    prescription_item: 'item-1',
    alert_type: 'dose',
    severity: 'contraindication',
    status: 'flagged',
    message: 'Dose acima do intervalo seguro.',
    recommendation: 'Reveja a dose; confirme peso/idade ou ajuste para o intervalo esperado.',
    ...overrides,
  }
}

describe('isDoseSafetyBlock', () => {
  it('returns the body for a 409 ApiError with code dose_safety_block and alerts', () => {
    const body = {
      code: 'dose_safety_block',
      detail: 'Dose fora do intervalo seguro.',
      alerts: [makeAlert()],
    }
    const err = new ApiError(409, body)
    expect(isDoseSafetyBlock(err)).toEqual(body)
  })

  it('returns null for a 409 without the dose_safety_block code', () => {
    const err = new ApiError(409, { code: 'something_else', alerts: [] })
    expect(isDoseSafetyBlock(err)).toBeNull()
  })

  it('returns null for a non-409 ApiError even with the code', () => {
    const err = new ApiError(400, { code: 'dose_safety_block', alerts: [] })
    expect(isDoseSafetyBlock(err)).toBeNull()
  })

  it('returns null when alerts is missing/not an array', () => {
    const err = new ApiError(409, { code: 'dose_safety_block' })
    expect(isDoseSafetyBlock(err)).toBeNull()
  })

  it('returns null for non-ApiError values', () => {
    expect(isDoseSafetyBlock(new Error('boom'))).toBeNull()
    expect(isDoseSafetyBlock(null)).toBeNull()
    expect(isDoseSafetyBlock({ code: 'dose_safety_block', alerts: [] })).toBeNull()
  })
})

describe('isWeightGate', () => {
  it('is true when the recommendation starts with the weight-gate constant', () => {
    const alert = makeAlert({
      recommendation: 'Registre/atualize o peso do paciente e reavalie.',
    })
    expect(isWeightGate(alert)).toBe(true)
  })

  it('is false for any other recommendation', () => {
    expect(isWeightGate(makeAlert())).toBe(false)
    expect(isWeightGate(makeAlert({ recommendation: 'Outra recomendação.' }))).toBe(false)
  })

  it('is true when blocking_kind is weight_gate even if the recommendation copy differs', () => {
    const alert = makeAlert({
      blocking_kind: 'weight_gate',
      recommendation: 'Copy completamente diferente.',
    })
    expect(isWeightGate(alert)).toBe(true)
  })

  it('is false when blocking_kind is out_of_range', () => {
    const alert = makeAlert({ blocking_kind: 'out_of_range' })
    expect(isWeightGate(alert)).toBe(false)
  })

  it('still falls back to the copy when blocking_kind is absent', () => {
    const alert = makeAlert({
      recommendation: 'Registre/atualize o peso do paciente e reavalie.',
    })
    expect(alert.blocking_kind).toBeUndefined()
    expect(isWeightGate(alert)).toBe(true)
  })
})

describe('acknowledgeDoseAlert', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('POSTs the reason to the acknowledge endpoint', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))

    await acknowledgeDoseAlert('alert-1', 'Justificativa clínica adequada.')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/safety-alerts/alert-1/acknowledge/',
      expect.objectContaining({ method: 'POST' }),
    )
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({ reason: 'Justificativa clínica adequada.' })
  })
})
