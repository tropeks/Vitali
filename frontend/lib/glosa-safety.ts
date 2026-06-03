/**
 * Glosa-safety interception helpers (PR G2 — deterministic glosa engine).
 *
 * Closing a TISS batch POSTs the `close` action and returns HTTP 409 with a
 * `glosa_safety_block` body when the deterministic glosa engine raises a
 * blocking alert on one or more guides. The biller must acknowledge each
 * blocking alert (with a justification) per guide and retry the close.
 *
 * A second 409 shape (`batch_modified_during_close`) means the batch guide set
 * changed mid-close → the UI must refetch the batch and let the user retry.
 *
 * The reachable interception point wired in the UI is the batch-close gate
 * (see app/(dashboard)/billing/batches/[id]/page.tsx).
 */
import { ApiError, apiFetch } from './api'

export interface GlosaAlert {
  id: string
  check_code: string
  severity: string
  message: string
  recommendation: string
  guide_item?: string
}

export interface GlosaGuideBlock {
  guide_id: string
  guide_number: string
  alerts: GlosaAlert[]
}

export interface GlosaSafetyBlock {
  code: 'glosa_safety_block'
  detail: string
  guides: GlosaGuideBlock[]
}

/**
 * Returns the parsed block body when `err` is an ApiError carrying a 409
 * `glosa_safety_block` response (with a guides array), otherwise null.
 */
export function isGlosaSafetyBlock(err: unknown): GlosaSafetyBlock | null {
  if (!(err instanceof ApiError)) return null
  if (err.status !== 409) return null
  const body = err.body
  if (
    body &&
    typeof body === 'object' &&
    body.code === 'glosa_safety_block' &&
    Array.isArray(body.guides)
  ) {
    return body as GlosaSafetyBlock
  }
  return null
}

/**
 * Returns true when `err` is an ApiError carrying a 409
 * `batch_modified_during_close` response — the batch guide set changed mid-close
 * and the caller must refetch the batch before retrying.
 */
export function isBatchModifiedDuringClose(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false
  if (err.status !== 409) return false
  const body = err.body
  return Boolean(
    body && typeof body === 'object' && body.code === 'batch_modified_during_close',
  )
}

/**
 * Acknowledge a blocking glosa alert with a billing justification, then the
 * caller retries the close. POSTs to the shared acknowledge endpoint.
 * BLOCK alerts require a reason >= 10 chars (backend 400s otherwise).
 */
export async function acknowledgeGlosaAlert(alertId: string, reason: string): Promise<void> {
  await apiFetch(`/api/v1/billing/glosa-safety-alerts/${alertId}/acknowledge/`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}
