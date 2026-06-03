import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  isGlosaSafetyBlock,
  isBatchModifiedDuringClose,
  acknowledgeGlosaAlert,
} from './glosa-safety'

vi.mock('./auth', () => ({
  getAccessToken: () => 'test-token',
}))

const blockBody = {
  code: 'glosa_safety_block',
  detail: 'Risco de glosa em uma ou mais guias.',
  guides: [
    {
      guide_id: 'g-1',
      guide_number: 'GUIA-001',
      alerts: [
        {
          id: 'alert-1',
          check_code: 'duplicate',
          severity: 'block',
          message: 'Procedimento já apresentado em outra guia.',
          recommendation: 'Remova a duplicidade.',
          guide_item: 'gi-1',
        },
      ],
    },
  ],
}

describe('isGlosaSafetyBlock', () => {
  it('returns the parsed block for a 409 glosa_safety_block ApiError', () => {
    const err = new ApiError(409, blockBody)
    const result = isGlosaSafetyBlock(err)
    expect(result).not.toBeNull()
    expect(result?.code).toBe('glosa_safety_block')
    expect(result?.guides).toHaveLength(1)
  })

  it('returns null for a non-ApiError', () => {
    expect(isGlosaSafetyBlock(new Error('boom'))).toBeNull()
    expect(isGlosaSafetyBlock(null)).toBeNull()
    expect(isGlosaSafetyBlock({ status: 409, body: blockBody })).toBeNull()
  })

  it('returns null for a 409 with a different code', () => {
    expect(isGlosaSafetyBlock(new ApiError(409, { code: 'batch_modified_during_close' }))).toBeNull()
  })

  it('returns null for the right code but wrong status', () => {
    expect(isGlosaSafetyBlock(new ApiError(400, blockBody))).toBeNull()
  })

  it('returns null when guides is not an array', () => {
    expect(
      isGlosaSafetyBlock(new ApiError(409, { code: 'glosa_safety_block', guides: 'nope' })),
    ).toBeNull()
  })
})

describe('isBatchModifiedDuringClose', () => {
  it('returns true for a 409 batch_modified_during_close ApiError', () => {
    expect(
      isBatchModifiedDuringClose(
        new ApiError(409, { code: 'batch_modified_during_close', detail: 'mudou' }),
      ),
    ).toBe(true)
  })

  it('returns false for a glosa block', () => {
    expect(isBatchModifiedDuringClose(new ApiError(409, blockBody))).toBe(false)
  })

  it('returns false for non-ApiError and wrong status', () => {
    expect(isBatchModifiedDuringClose(new Error('boom'))).toBe(false)
    expect(
      isBatchModifiedDuringClose(new ApiError(400, { code: 'batch_modified_during_close' })),
    ).toBe(false)
  })
})

describe('acknowledgeGlosaAlert', () => {
  const mockFetch = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = mockFetch as unknown as typeof fetch
    mockFetch.mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
      json: async () => ({}),
      text: async () => '',
    } as Response)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('POSTs the reason to the glosa-safety acknowledge endpoint', async () => {
    await acknowledgeGlosaAlert('alert-1', 'Justificativa válida do faturamento.')

    expect(mockFetch).toHaveBeenCalledTimes(1)
    const [url, init] = mockFetch.mock.calls[0]
    expect(String(url)).toBe('/api/v1/billing/glosa-safety-alerts/alert-1/acknowledge/')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      reason: 'Justificativa válida do faturamento.',
    })
  })
})
