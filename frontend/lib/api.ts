/**
 * Centralized fetch wrapper for Vitali frontend.
 *
 * Handles:
 *   - PASSWORD_CHANGE_REQUIRED 403 → redirect to /auth/change-password (T5/T12)
 *   - single-flight JWT refresh + one retry on 401
 *   - expired refresh session cleanup + redirect to login preserving `next`
 *
 * The JWT itself is never read or attached client-side: `/api/*` is served by
 * the Next.js proxy (app/api/[...path]/route.ts), which reads the httpOnly
 * access_token cookie on the server and injects the Authorization header
 * before forwarding to Django. The browser sends the httpOnly cookie
 * automatically (fetch's default credentials mode is same-origin) — a fresh
 * access_token cookie from /api/auth/refresh is picked up on the very next
 * request with no client-side bookkeeping.
 *
 * Usage:
 *   const data = await apiFetch('/api/v1/me')
 *   const result = await apiFetch('/api/v1/hr/employees/', {
 *     method: 'POST',
 *     body: JSON.stringify(payload),
 *   })
 */

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
  const headers = new Headers(fetchInit.headers)
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

/** Result of {@link apiFetchWithStatus} — payload plus the raw HTTP status,
 * needed by callers that must tell an idempotent 200 apart from a fresh 201. */
export interface ApiFetchResult<T> {
  data: T
  status: number
}

export async function apiFetchWithStatus<T = any>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<ApiFetchResult<T>> {
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
    return { data: undefined as T, status: response.status }
  }

  // Try JSON; fall back to text
  const contentType = response.headers.get('content-type') ?? ''
  const data = contentType.includes('application/json')
    ? await response.json()
    : ((await response.text()) as unknown as T)
  return { data, status: response.status }
}

/**
 * Thin wrapper over {@link apiFetchWithStatus} that drops the status and
 * returns just the payload — the shape most callers want.
 */
export async function apiFetch<T = any>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const { data } = await apiFetchWithStatus<T>(path, options)
  return data
}
