/**
 * Content-Security-Policy construction (issue #115 — activate deferred CSP enforcement).
 *
 * The CSP violation collector (Django: POST /api/v1/security/csp-report) shipped in
 * S28-05, but emitting the header itself was deferred. This module builds a
 * nonce-based policy that the Next.js middleware attaches to every browser-facing
 * response.
 *
 * Rollout matches the collector's documented design: ship Report-Only first — it
 * never blocks, only POSTs violations to the collector — confirm a clean report over
 * the soak window, then promote to enforcing by setting `CSP_ENFORCE=true`.
 */

/**
 * Same-origin path the browser POSTs violation reports to. Keep the trailing slash:
 * browsers do not follow redirects for CSP reports reliably, and Django's URLConf
 * expects the slash.
 */
export const CSP_REPORT_PATH = "/api/v1/security/csp-report/";

/** Header carrying the per-request nonce to Server Components that render scripts. */
export const NONCE_HEADER = "x-nonce";

/** A per-request base64 nonce from the Web Crypto API (Edge-runtime safe). */
export function generateNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export interface CspOptions {
  nonce: string;
  /** Dev needs 'unsafe-eval' for React Refresh / webpack HMR; never set in prod. */
  isDev?: boolean;
  /** Only the enforcing policy should include browser-upgrade directives. */
  enforce?: boolean;
}

/**
 * Build the policy string. Directive choices:
 * - `script-src`: nonce + 'strict-dynamic' lets the nonce'd Next.js bootstrap pull
 *   its chunked scripts without enumerating hashes; modern browsers then ignore the
 *   'self'/host allowlist for scripts, which is the intended hardening.
 * - `style-src 'unsafe-inline'`: React inline `style` props and Next.js critical-CSS
 *   injection need it. Style injection is not a script-execution vector, so this does
 *   not weaken the XSS defence that `script-src` provides.
 * - `connect-src https: wss:`: same-origin API plus Sentry ingest + session replay,
 *   without hardcoding the deploy-specific DSN host.
 * - `worker-src blob:`: Sentry Session Replay runs in a Worker created from a blob URL.
 */
export function buildContentSecurityPolicy({
  nonce,
  isDev = false,
  enforce = false,
}: CspOptions): string {
  const scriptSrc = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    ...(isDev ? ["'unsafe-eval'"] : []),
  ];

  const directives: Array<[string, string[] | null]> = [
    ["default-src", ["'self'"]],
    ["base-uri", ["'self'"]],
    ["script-src", scriptSrc],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:", "blob:", "https:"]],
    ["font-src", ["'self'", "data:"]],
    ["connect-src", ["'self'", "https:", "wss:"]],
    ["worker-src", ["'self'", "blob:"]],
    ["manifest-src", ["'self'"]],
    ["frame-src", ["'self'"]],
    ["frame-ancestors", ["'none'"]],
    ["form-action", ["'self'"]],
    ["object-src", ["'none'"]],
    // Boolean directive (no value). Only meaningful when the policy is enforcing.
    ...(enforce && !isDev
      ? ([["upgrade-insecure-requests", null]] as Array<[string, null]>)
      : []),
  ];

  const serialized = directives.map(([key, vals]) =>
    vals === null ? key : `${key} ${vals.join(" ")}`,
  );
  serialized.push(`report-uri ${CSP_REPORT_PATH}`);
  return serialized.join("; ");
}

/** Response header name for the policy, by enforcement mode. */
export function cspHeaderName(enforce: boolean): string {
  return enforce ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only";
}

/**
 * Static security headers for browser-facing Next.js responses. Django sets these
 * for API responses (settings/production.py), but the Node server that renders the
 * app pages does not — so we set them here for the document responses too.
 */
export const STATIC_SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(self), geolocation=(), payment=()",
};
