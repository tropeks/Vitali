/**
 * Centralized fetch wrapper for Vitali frontend.
 *
 * Handles:
 *   - JWT Authorization header injection (uses getAccessToken from lib/auth)
 *   - PASSWORD_CHANGE_REQUIRED 403 → redirect to /auth/change-password (T5/T12)
 *   - single-flight JWT refresh + one retry on 401
 *   - expired refresh session cleanup + redirect to login preserving `next`
 *
 * Usage:
 *   const data = await apiFetch('/api/v1/me')
 *   const result = await apiFetch('/api/v1/hr/employees/', {
 *     method: 'POST',
 *     body: JSON.stringify(payload),
 *   })
 */
import { getAccessToken } from './auth'

let refreshInFlight: Promise<Response> | null = null

export interface ApiFetchOptions extends RequestInit {
  /** If true, do NOT auto-redirect on PASSWORD_CHANGE_REQUIRED — let caller handle. */
  skipPasswordChangeRedirect?: boolean
}

export class ApiError extends Error {
  status: number
  body: any
  constructor(status: number, body: any, message?: string) {
    super(message ?? `API error ${status}`)
    this.status = status
    this.body = body
  }
}

function fetchWithAccessToken(path: string, fetchInit: RequestInit): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(fetchInit.headers)
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return fetch(path, { ...fetchInit, headers })
}

function refreshAccessToken(): Promise<Response> {
  if (!refreshInFlight) {
    refreshInFlight = fetch('/api/auth/refresh', {
      method: 'POST',
      credentials: 'same-origin',
    }).finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

async function redirectExpiredSession(): Promise<never> {
  // The logout route clears every auth cookie even if Django is unavailable.
  await fetch('/api/auth/logout', {
    method: 'POST',
    credentials: 'same-origin',
  }).catch(() => undefined)

  const next = `${window.location.pathname || '/'}${window.location.search || ''}`
  window.location.href = `/login?next=${encodeURIComponent(next)}`
  throw new ApiError(401, { detail: 'Session expired.' }, 'Sessão expirada — redirecionando')
}

export async function apiFetch<T = any>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const { skipPasswordChangeRedirect, ...fetchInit } = options

  const headers = new Headers(fetchInit.headers)
  // Default content-type for JSON bodies (when caller provides a string body)
  if (
    fetchInit.body &&
    typeof fetchInit.body === 'string' &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }

  let response = await fetchWithAccessToken(path, { ...fetchInit, headers })

  // Browser API calls get one transparent refresh/retry. Concurrent 401s share
  // the same refresh request so SimpleJWT token rotation cannot race itself.
  if (
    response.status === 401 &&
    typeof window !== 'undefined' &&
    !path.startsWith('/api/auth/')
  ) {
    const refreshed = await refreshAccessToken()
    if (refreshed.ok) {
      response = await fetchWithAccessToken(path, { ...fetchInit, headers })
      if (response.status === 401) {
        return redirectExpiredSession()
      }
    } else if (refreshed.status === 401) {
      return redirectExpiredSession()
    }
  }

  // Handle PASSWORD_CHANGE_REQUIRED redirect (T5 contract)
  if (response.status === 403 && !skipPasswordChangeRedirect) {
    const cloned = response.clone()
    try {
      const body = await cloned.json()
      const code = body?.error?.code
      const redirect = body?.error?.redirect
      if (code === 'PASSWORD_CHANGE_REQUIRED' && redirect && typeof window !== 'undefined') {
        window.location.href = redirect
        // Throw to short-circuit the caller — they shouldn't proceed
        throw new ApiError(403, body, 'PASSWORD_CHANGE_REQUIRED — redirecting')
      }
    } catch (jsonErr) {
      if (jsonErr instanceof ApiError) throw jsonErr
      // Not a JSON 403 or different error — fall through to normal error path
    }
  }

  if (!response.ok) {
    let body: any
    try {
      body = await response.json()
    } catch {
      body = await response.text().catch(() => null)
    }
    throw new ApiError(response.status, body)
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T
  }

  // Try JSON; fall back to text
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  return response.text() as unknown as T
}
