/**
 * Tests for lib/api.ts — apiFetch wrapper.
 *
 * NOTE: Vitest is not installed in this project (no vitest in package.json).
 * These tests are written to the Vitest API so they can be run once vitest
 * is added as a devDependency (Sprint 19+). To add:
 *   npm install --save-dev vitest @vitest/coverage-v8
 * and add a vitest.config.ts referencing the Next.js tsconfig paths.
 *
 * Run (once set up): npx vitest run lib/api.test.ts
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { apiFetch, ApiError } from './api'

// ─── Mock lib/auth ─────────────────────────────────────────────────────────────

vi.mock('./auth', () => ({
  getAccessToken: vi.fn(() => null),
}))

import { getAccessToken } from './auth'
const mockGetAccessToken = vi.mocked(getAccessToken)

// ─── Helpers ───────────────────────────────────────────────────────────────────

function makeResponse(status: number, body: unknown, contentType = 'application/json'): Response {
  const bodyStr = typeof body === 'string' ? body : JSON.stringify(body)
  return new Response(bodyStr, {
    status,
    headers: { 'Content-Type': contentType },
  })
}

// ─── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  mockGetAccessToken.mockReturnValue(null)

  // Allow setting window.location.href
  Object.defineProperty(window, 'location', {
    value: { href: '', pathname: '/patients', search: '?page=2' },
    writable: true,
    configurable: true,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ─── Tests ─────────────────────────────────────────────────────────────────────

describe('apiFetch', () => {
  it('passes through 200 OK and returns parsed JSON', async () => {
    const payload = { id: 1, name: 'Test' }
    vi.mocked(fetch).mockResolvedValue(makeResponse(200, payload))

    const result = await apiFetch('/api/v1/me')

    expect(result).toEqual(payload)
  })

  it('redirects to /auth/change-password on PASSWORD_CHANGE_REQUIRED 403', async () => {
    const body403 = { error: { code: 'PASSWORD_CHANGE_REQUIRED', redirect: '/auth/change-password' } }
    vi.mocked(fetch).mockResolvedValue(makeResponse(403, body403))

    await expect(apiFetch('/api/v1/something')).rejects.toThrow(ApiError)

    expect(window.location.href).toBe('/auth/change-password')
  })

  it('throws ApiError on PASSWORD_CHANGE_REQUIRED 403', async () => {
    const body403 = { error: { code: 'PASSWORD_CHANGE_REQUIRED', redirect: '/auth/change-password' } }
    vi.mocked(fetch).mockResolvedValue(makeResponse(403, body403))

    let caught: unknown
    try {
      await apiFetch('/api/v1/something')
    } catch (e) {
      caught = e
    }

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(403)
  })

  it('does NOT redirect on other 403 codes (e.g. MFA_REQUIRED)', async () => {
    const body403 = { error: { code: 'MFA_REQUIRED', redirect: '/auth/mfa' } }
    vi.mocked(fetch).mockResolvedValue(makeResponse(403, body403))

    window.location.href = ''

    let caught: unknown
    try {
      await apiFetch('/api/v1/something')
    } catch (e) {
      caught = e
    }

    // Should not have touched window.location (only PASSWORD_CHANGE_REQUIRED triggers redirect)
    expect(window.location.href).toBe('')
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(403)
  })

  it('throws ApiError with correct status on 5xx', async () => {
    vi.mocked(fetch).mockResolvedValue(makeResponse(500, { detail: 'Internal Server Error' }))

    let caught: unknown
    try {
      await apiFetch('/api/v1/something')
    } catch (e) {
      caught = e
    }

    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(500)
  })

  it('injects Authorization header when getAccessToken returns a token', async () => {
    mockGetAccessToken.mockReturnValue('tok123')
    vi.mocked(fetch).mockResolvedValue(makeResponse(200, { ok: true }))

    await apiFetch('/api/v1/me')

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const headers = init?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer tok123')
  })

  it('refreshes once and retries a 401 with the rotated access token', async () => {
    mockGetAccessToken
      .mockReturnValueOnce('expired-token')
      .mockReturnValueOnce('rotated-token')
    vi.mocked(fetch)
      .mockResolvedValueOnce(makeResponse(401, { detail: 'Token expired' }))
      .mockResolvedValueOnce(makeResponse(200, { ok: true }))
      .mockResolvedValueOnce(makeResponse(200, { id: 7 }))

    await expect(apiFetch('/api/v1/me')).resolves.toEqual({ id: 7 })

    expect(vi.mocked(fetch).mock.calls[1][0]).toBe('/api/auth/refresh')
    const retryHeaders = vi.mocked(fetch).mock.calls[2][1]?.headers as Headers
    expect(retryHeaders.get('Authorization')).toBe('Bearer rotated-token')
  })

  it('clears the session and redirects to login when refresh is expired', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(makeResponse(401, { detail: 'Token expired' }))
      .mockResolvedValueOnce(makeResponse(401, { error: 'Token inválido.' }))
      .mockResolvedValueOnce(makeResponse(200, { ok: true }))

    await expect(apiFetch('/api/v1/me')).rejects.toMatchObject({ status: 401 })

    expect(vi.mocked(fetch).mock.calls[2][0]).toBe('/api/auth/logout')
    expect(window.location.href).toBe('/login?next=%2Fpatients%3Fpage%3D2')
  })

  it('uses a single refresh for concurrent 401 responses', async () => {
    let releaseRefresh: ((response: Response) => void) | undefined
    const refreshResponse = new Promise<Response>((resolve) => { releaseRefresh = resolve })
    mockGetAccessToken.mockReturnValue('rotated-token')
    vi.mocked(fetch).mockImplementation((path) => {
      if (path === '/api/auth/refresh') return refreshResponse
      const apiCalls = vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/v1/me').length
      return Promise.resolve(apiCalls <= 2
        ? makeResponse(401, { detail: 'Token expired' })
        : makeResponse(200, { ok: true }))
    })

    const requests = [apiFetch('/api/v1/me'), apiFetch('/api/v1/me')]
    await Promise.resolve()
    releaseRefresh?.(makeResponse(200, { ok: true }))

    await expect(Promise.all(requests)).resolves.toEqual([{ ok: true }, { ok: true }])
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/auth/refresh')).toHaveLength(1)
  })

  it('does NOT redirect when skipPasswordChangeRedirect=true even on PASSWORD_CHANGE_REQUIRED', async () => {
    const body403 = { error: { code: 'PASSWORD_CHANGE_REQUIRED', redirect: '/auth/change-password' } }
    vi.mocked(fetch).mockResolvedValue(makeResponse(403, body403))

    window.location.href = ''

    let caught: unknown
    try {
      await apiFetch('/api/v1/something', { skipPasswordChangeRedirect: true })
    } catch (e) {
      caught = e
    }

    // No redirect should occur
    expect(window.location.href).toBe('')
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(403)
  })
})
