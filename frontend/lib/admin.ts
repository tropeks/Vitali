import { ApiError } from '@/lib/api'

export type ListResponse<T> = T[] | { results: T[] }

export function listResults<T>(data: ListResponse<T>): T[] {
  return Array.isArray(data) ? data : data.results ?? []
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback
  const body = error.body
  if (typeof body?.detail === 'string') return body.detail
  if (typeof body?.status === 'string') return body.status
  if (Array.isArray(body) && body[0]) return String(body[0])
  if (body && typeof body === 'object') {
    const first = Object.values(body).flat()[0]
    if (first) return String(first)
  }
  return fallback
}
